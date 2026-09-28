API_KEY = "6e848f866041408f867d36b7cf265967.5KjEpDkMPRnogsj1"
BASE_AI_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL_NAME = "glm-4-flash"
choose_job_use_ai=True
use_local_codebuddy=True
# 调用codebuddy时默认使用的模型
CODEBUDDY_MODEL="glm-5.3-flash"
# 本地codebuddy daemon地址（codebuddy daemon start后，用 codebuddy daemon status 查看 endpoint）
CODEBUDDY_DAEMON_URL="http://127.0.0.1:8000"
use_local_model=True
private_data=False
model_file_path = "./model_file/Qwen3.5-4B-Q4_K_M.gguf"

# workbuddy 官网地址（用户需先在浏览器中登录该页面）
# 切换到 workbuddy 执行时弹窗会显示该地址，点“是”提交时前端直接在新标签页打开它
WORKBUDDY_URL = "https://www.workbuddy.cn/app"