# -*- coding: utf-8 -*-
"""
本地大模型（GGUF）加载与对话。

- 仅当 config.use_local_model 为 True 时才会加载模型（进程启动时可调用 preload 预加载）
- 单例懒加载 + 双重检查锁，整个进程只加载一次
- llama_cpp 延迟导入：use_local_model=False 时不需要安装/加载该库
- 推理加锁串行化，避免并发请求损坏 llama.cpp 内部状态
"""
import os
import threading

import config

_model = None
_load_lock = threading.Lock()
# 本地推理串行化（llama.cpp 推理期间会释放 GIL，并发调用不安全）
_infer_lock = threading.Lock()

# 上下文长度/生成上限（4B Q4 模型，8k 上下文在 Mac 内存下无压力）
N_CTX = 8192
MAX_TOKENS = 1024


def _resolve_model_path():
    # config.model_file_path 支持相对路径（相对于项目根目录），避免依赖启动时的工作目录
    path = config.model_file_path
    if not os.path.isabs(path):
        project_root = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(project_root, path)
    return os.path.normpath(path)


def get_model():
    """获取本地模型单例，首次调用时加载（约 2.6G，需数秒）"""
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                # 延迟导入：不使用本地模型时无需加载 llama_cpp
                from llama_cpp import Llama

                model_path = _resolve_model_path()
                if not os.path.exists(model_path):
                    raise FileNotFoundError(f"本地模型文件不存在: {model_path}")
                print(f"[local_model] 正在加载本地模型: {model_path} ...", flush=True)
                # n_gpu_layers=-1 时 llama.cpp 会自动把全部层放到 GPU（Metal）；
                # 不支持时内部自动回退 CPU，无需特殊处理
                _model = Llama(
                    model_path=model_path,
                    n_ctx=N_CTX,
                    n_gpu_layers=-1,
                    verbose=False,
                )
                print("[local_model] 本地模型加载完成", flush=True)
    return _model


def preload():
    """进程启动时预加载（一上来就把模型读进内存）"""
    get_model()


def call_local(user_msg, system_prompt, memory_msg=None):
    """
    与 common.call_glm 相同的入参/返回约定：
    :param user_msg: 用户最新消息
    :param system_prompt: 系统人设
    :param memory_msg: [{"role": "user"/"assistant", "content": ...}, ...]
    :return: 助手回复文本；异常时返回 False
    """
    try:
        llm = get_model()
    except Exception as e:
        print(f"[local_model] 模型加载失败: {e}")
        return False

    messages = [{"role": "system", "content": system_prompt or ""}]
    if memory_msg:
        messages.extend(memory_msg)
    messages.append({"role": "user", "content": user_msg})

    with _infer_lock:
        try:
            # Qwen3 系模型默认开启 thinking，这里关掉，避免输出冗长思考、拖慢 4B 小模型；
            # 旧版 llama-cpp-python 不支持该参数时自动回退
            try:
                resp = llm.create_chat_completion(
                    messages=messages,
                    temperature=0.7,
                    max_tokens=MAX_TOKENS,
                    chat_template_kwargs={"enable_thinking": False},
                )
            except TypeError:
                resp = llm.create_chat_completion(
                    messages=messages,
                    temperature=0.7,
                    max_tokens=MAX_TOKENS,
                )
        except Exception as e:
            print(f"[local_model] 本地推理失败: {e}")
            return False

    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return False


if __name__ == "__main__":
    print(call_local("你好，用一句话介绍你自己", "你是一名口语化、回答简短的助理"))
