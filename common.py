import requests
import config


def call_ai(user_msg, system_prompt, memory_msg=[], use_local=False):
    """
    统一大模型入口：所有原来调用 call_glm 的地方改调这里。
    :param use_local: True=不消耗token，走本地GGUF模型；False=消耗token，走云端GLM
    """
    if use_local and getattr(config, "use_local_model", False):
        # 延迟导入：未启用本地模型时不加载 llama_cpp
        from local_model import call_local
        return call_local(user_msg, system_prompt, memory_msg)
    return call_glm(user_msg, system_prompt, memory_msg)


def call_glm(user_msg, system_prompt, memory_msg = []):
    """
    :param user_msg:
    :param system_prompt:
    :param memory_msg:
    :return:
    """
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.7
    }
    if memory_msg != []:
        messages = [{"role": "system", "content": system_prompt}] + memory_msg + [{"role": "user", "content": user_msg}]
        payload = {
            "model": config.MODEL_NAME,
            "messages": messages,
            "temperature": 0.7
        }
    resp = requests.post(f"{config.BASE_AI_URL}", headers=headers, json=payload)
    res_json = resp.json()
    try:
        if "choices" in res_json:
            return res_json["choices"][0]["message"]["content"]
        else:
            return res_json
    except:
        return False


if __name__ == '__main__':
    system_prompt="""你是一名助理，现在老板提出了需求，你现在根据他给到的需求，找到对应职业的人。
            对话规则：
            1.只输出1名职业名称。
            2.语言简短口语化，不要长篇大论。"""
    print(call_glm("帮我敲下这代码",system_prompt))

