import os
import shutil
import time
import uuid

import requests
from flask import Flask, request, jsonify, session
from werkzeug.utils import secure_filename
from common import call_ai
from search_job import search_job
from doc_reader import extract_text, truncate_for_model
import json
import config

app = Flask(__name__)
# 使用session必须设置secret_key
app.secret_key = "no-agent-be-boss-secret-key"
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
# 上传文件大小上限 20MB
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

# codebuddy daemon WebUI/REST 根地址，codebuddy daemon start 后默认监听本地
CODEBUDDY_API_ROOT = config.CODEBUDDY_DAEMON_URL.rstrip("/")
# daemon 要求所有 /api 请求带该头（CSRF 防护，值任意非空即可）
CODEBUDDY_HEADERS = {"x-codebuddy-request": "1", "Content-Type": "application/json"}
# 任务产物根目录：必须位于 codebuddy settings.json 的 trustedDirectories 内，
# 本项目目录已被信任（NoAgentBeBoss/**），任务子目录建在项目下即可免确认直接执行
TASK_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codebuddy_tasks")
# 用户上传文档的保存根目录
UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

# 文档摘要较长，不放进cookie session；按session中的uid在服务端保存
# {uid: [{"id", "name", "summary", "path"}, ...]}
FILE_STORE = {}

SYSTEM_PROMPT = ""

FILE_SUMMARY_SYSTEM = """
你是文档摘要助理。请阅读用户给出的文档原文，输出一份精简的中文内容摘要：
1. 保留关键事实、核心数据、重要结论和待办事项，去掉套话、重复内容和格式噪音。
2. 摘要控制在300字以内，条理清晰，必要时可分点。
3. 只输出摘要本身，不要输出多余解释。
"""


def use_local_model():
    """session中记录的对话模式：True=不消耗token走本地模型，False=消耗token走云端GLM"""
    return bool(session.get("use_local", False))


def get_uid():
    """每个浏览器会话一个服务端uid（只把很短的uid放cookie）"""
    uid = session.get("uid")
    if not uid:
        uid = uuid.uuid4().hex
        session["uid"] = uid
    return uid


def build_file_context():
    """把当前会话已上传文件的摘要拼成可注入system prompt的上下文段"""
    files = FILE_STORE.get(session.get("uid"), [])
    if not files:
        return ""
    parts = ["【老板上传的参考资料摘要】"]
    for idx, f in enumerate(files, 1):
        parts.append(f"资料{idx}《{f['name']}》：{f['summary']}")
    parts.append("与老板对话及后续执行任务时，请结合以上参考资料内容。")
    return "\n".join(parts)


def with_file_context(system_prompt):
    """在system prompt末尾追加已上传文件的摘要上下文"""
    context = build_file_context()
    if not context:
        return system_prompt
    return f"{system_prompt or ''}\n\n{context}"


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"status": "error", "message": "文件不能超过20MB"}), 413

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route("/app_config", methods=['GET'])
def app_config():
    # 告诉前端本地模型能力是否可用（不可用时前端“不消耗token”选项不可选）
    return jsonify({"use_local_model": bool(getattr(config, "use_local_model", False))})

@app.route("/set_chat_mode", methods=['POST'])
def set_chat_mode():
    data = request.get_json(silent=True) or {}
    use_local = bool(data.get("use_local", False))
    # 本地模型未启用时，不允许切到“不消耗token”模式
    if use_local and not getattr(config, "use_local_model", False):
        return jsonify({"status": "error", "message": "本地模型未启用"}), 400
    session["use_local"] = use_local
    return jsonify({"status": "ok", "use_local": use_local})

@app.route("/upload_file", methods=['POST'])
def upload_file():
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"status": "error", "message": "未收到文件"}), 400

    uid = get_uid()
    safe_name = secure_filename(f.filename) or f"file_{uuid.uuid4().hex[:8]}"
    file_id = uuid.uuid4().hex[:12]
    save_dir = os.path.join(UPLOAD_ROOT, uid)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{file_id}_{safe_name}")
    f.save(save_path)

    # 1. 用 markitdown 提取文档原文
    text = extract_text(save_path)
    if not text:
        os.remove(save_path)
        return jsonify({"status": "error",
                        "message": f"《{f.filename}》解析失败或内容为空，支持PDF/Word/PPT/Excel/TXT等格式"}), 400

    # 2. 按当前对话模式截断后，调用大模型生成精简摘要（消耗token走云端，不消耗走本地）
    use_local = use_local_model()
    summary = call_ai(truncate_for_model(text, use_local), FILE_SUMMARY_SYSTEM,
                      use_local=use_local)
    if not summary:
        os.remove(save_path)
        return jsonify({"status": "error", "message": "文档摘要生成失败，请重试"}), 500

    # 3. 存服务端，后续每轮对话自动注入system prompt
    FILE_STORE.setdefault(uid, []).append({
        "id": file_id,
        "name": f.filename,
        "summary": summary.strip(),
        "path": save_path,
    })
    return jsonify({"status": "ok", "file": {"id": file_id, "name": f.filename}})

@app.route("/remove_file", methods=['POST'])
def remove_file():
    data = request.get_json(silent=True) or {}
    file_id = data.get("id", "")
    uid = session.get("uid")
    files = FILE_STORE.get(uid, [])
    for f in files:
        if f["id"] == file_id:
            try:
                os.remove(f["path"])
            except OSError:
                pass
            files.remove(f)
            return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "文件不存在"}), 404

@app.route("/get_job_man", methods=['POST'])
def get_job_man():
    data = request.get_json()
    user_message = data.get("message", "")
    reply = search_job(user_message, use_local=use_local_model())
    return jsonify({"reply": reply})

@app.route("/reset_prompt", methods=['POST'])
def reset_prompt():
    data = request.get_json()
    user_message = data.get("message", "")
    try:
        task, job = json.loads(user_message)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "参数格式错误"}), 400
    session["SYSTEM_PROMPT"] = f"""
    你扮演员工，和老板对话，老板说的任务是{task}。
    你的人设：{job}。
    对话规则：
    1. 不要一次性输出结果，循序渐进提问，收集任务所需的需求。
    2. 语言简短口语化，不要长篇大论。
    3. 如果你觉得需求收集差不多了，可以询问老板还有什么可补充的，是否可以开始干活
    """
    # 重置prompt时一并清空历史记忆
    session["memory"] = []
    return jsonify({"status": "ok"})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")
    system_prompt = session.get("SYSTEM_PROMPT")
    # 把已上传文件的摘要上下文追加进system prompt
    system_prompt = with_file_context(system_prompt)
    # 从session取出历史聊天作为记忆
    memory = session.get("memory", [])
    # 根据session里的模式选择：消耗token走云端GLM，否则走本地模型
    reply = call_ai(user_message, system_prompt, memory, use_local=use_local_model())
    # 把本轮对话追加进记忆
    memory.append({"role": "user", "content": user_message})
    memory.append({"role": "assistant", "content": reply})
    # session存cookie有大小限制，只保留最近20条，避免超长后报错
    session["memory"] = memory[-20:]
    return jsonify({"reply": reply})

@app.route("/reset_session", methods=['POST'])
def reset_session():
    # 清空前先按uid删掉服务端保存的上传文件及摘要
    uid = session.get("uid")
    if uid:
        FILE_STORE.pop(uid, None)
        shutil.rmtree(os.path.join(UPLOAD_ROOT, uid), ignore_errors=True)
    # 清空所有session（SYSTEM_PROMPT、memory等全部清除）
    session.clear()
    return jsonify({"status": "ok"})

GENERATE_PROMPT_SYSTEM = """
你是一名需求整理助理。老板和员工已经完成了任务需求沟通，请你根据上述对话内容，整理生成一份最终的任务执行prompt。
要求：
1. 明确角色身份、任务目标、具体需求细节和交付标准。
2. 结构清晰、内容完整，可以直接交给执行者照此完成任务。
3. 只输出prompt本身，不要输出多余的解释或寒暄。
"""

@app.route("/generate_prompt", methods=["POST"])
def generate_prompt():
    # 根据session里的历史聊天生成最终prompt（同样带上已上传文件的摘要上下文）
    memory = session.get("memory", [])
    prompt = call_ai("请根据以上对话，生成最终任务prompt。",
                     with_file_context(GENERATE_PROMPT_SYSTEM), memory,
                     use_local=use_local_model())
    if not prompt:
        return jsonify({"status": "error", "message": "生成失败，请重试"}), 500
    # 存一份到session，供调用codebuddy时使用
    session["generated_prompt"] = prompt
    return jsonify({"prompt": prompt})


def call_codebuddy_webui(prompt, cwd):
    """
    以“调用WebUI”的方式投递任务：和 codebuddy 工作台网页端完全一样，
    请求 daemon 的 POST /api/v1/jobs 创建后台任务，再轮询拿到 webUrl。
    :return: (job信息dict, 错误信息str)，成功时错误信息为 None
    """
    # 1. 创建后台任务（和网页端“新建任务”发出的请求一致）
    payload = {
        "prompt": prompt,
        "cwd": cwd,
        # default：每次调用工具都需要人工在工作台允许/拒绝
        "permissionMode": "default",
    }
    if getattr(config, "CODEBUDDY_MODEL", ""):
        payload["model"] = config.CODEBUDDY_MODEL
    try:
        resp = requests.post(f"{CODEBUDDY_API_ROOT}/api/v1/jobs",
                             headers=CODEBUDDY_HEADERS, json=payload, timeout=30)
    except requests.exceptions.RequestException:
        return None, "本地codebuddy服务未启动，请先执行 codebuddy daemon start"

    try:
        resp_json = resp.json()
    except ValueError:
        return None, f"codebuddy服务返回异常（HTTP {resp.status_code}）"
    if not resp.ok:
        return None, resp_json.get("error", {}).get("message", f"HTTP {resp.status_code}") \
            if isinstance(resp_json.get("error"), dict) else "提交codebuddy任务失败"

    job = resp_json.get("data", {})
    job_id = job.get("id")
    session_id = job.get("sessionId")
    if not job_id or not session_id:
        return None, "codebuddy未返回任务信息"

    # 2. worker 启动后任务详情里才有 webUrl（通常几秒内就绪），轮询等待一下
    web_url = job.get("webUrl")
    deadline = time.time() + 12
    while not web_url and time.time() < deadline:
        time.sleep(1)
        try:
            detail_resp = requests.get(f"{CODEBUDDY_API_ROOT}/api/v1/jobs/{job_id}",
                                       headers=CODEBUDDY_HEADERS, timeout=10)
            detail_job = detail_resp.json().get("data", {}).get("job", {})
        except (requests.exceptions.RequestException, ValueError):
            break
        web_url = detail_job.get("webUrl")
        # 任务提前结束（如启动即失败）就不再等
        if detail_job.get("settled"):
            break

    # 3. 拼接直达该会话的工作台链接；webUrl未就绪时退回到daemon主页面
    base = (web_url or CODEBUDDY_API_ROOT).rstrip("/")
    job["workbench_url"] = f"{base}/?sessionId={session_id}"
    return job, None


@app.route("/call_codebuddy", methods=['POST'])
def call_codebuddy():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("message") or "").strip()
    buddy_type = data.get("type") or "codebuddy"
    if not prompt:
        return jsonify({"status": "error", "message": "任务prompt不能为空"}), 400
    # 当前只接入了本地 codebuddy；workbuddy 没有本地 daemon
    if buddy_type != "codebuddy":
        return jsonify({"status": "error", "message": f"暂未接入{buddy_type}，目前仅支持本地codebuddy"}), 400

    # 每个任务一个独立产物目录，建在已信任的项目目录下
    task_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task_dir = os.path.join(TASK_ROOT, task_name)
    os.makedirs(task_dir, exist_ok=False)

    job, err = call_codebuddy_webui(prompt, task_dir)
    if err:
        return jsonify({"status": "error", "message": err}), 502

    return jsonify({
        "status": "ok",
        "job_id": job["id"],
        "session_id": job["sessionId"],
        # 产物落盘目录 & 直达工作台链接（前端已按这两个字段渲染）
        "task_dir": task_dir,
        "workbench_url": job["workbench_url"],
    })


if __name__ == '__main__':
    debug = True
    # use_local_model=True 时一上来就预加载本地模型；
    # debug 重载器模式下父监控进程不加载，只在真正对外服务的子进程加载
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if getattr(config, "use_local_model", False) and (not debug or is_reloader_child):
        import local_model
        local_model.preload()
    app.run(host='127.0.0.1', debug=debug)
