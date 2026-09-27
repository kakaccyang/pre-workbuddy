from bm25 import BM25
import sqlite3
import config
from common import call_ai
import json
# 1. 连接数据库，文件不存在会自动创建
conn = sqlite3.connect("./job.db")
# 获取游标
cur = conn.cursor()
chinese_docs = []

rows = cur.execute("SELECT * FROM job where type = 1").fetchall()
common_job = []
for r in rows:
    common_job.append(r[1]+"\t"+r[2])
rows = cur.execute("SELECT * FROM job where type = 0").fetchall()
other_job = []
for r in rows:
    other_job.append(r[1]+"\t"+r[2])
# 关闭连接
cur.close()
conn.close()
bm25_zh_common_job = BM25(common_job)
bm25_zh_other_job = BM25(other_job)



def search_job(query, use_local=False):
    """
    search with bm25 or ai + rag
    :param query:
    :param use_local: True=不消耗token走本地模型；False=消耗token走云端GLM
    :return:
    """
    job_list = ["自由职业","助理"]
    try:
        for idx, score, doc in bm25_zh_common_job.search(query, top_k=1):
            job_list.append(doc.split("\t")[0])
        if len(job_list) == 0:
            for idx, score, doc in bm25_zh_other_job.search(query, top_k=1):
                job_list.append(doc.split("\t")[0])
    except:
        print("there is something wrong!")
    if config.choose_job_use_ai:
        if len(job_list) == 0:
            system_prompt = """
            你是一名助理，现在老板提出了需求，你现在根据他给到的需求，找到对应职业的人。
            对话规则：
            1.只输出1名职业名称。
            2.语言简短口语化，不要长篇大论。
            """
            res = call_ai(query, system_prompt, use_local=use_local)
            if len(res) < 10:
                job_list.append(res)
        else:
            new_job_list = []
            for idx, score, doc in bm25_zh_common_job.search(query, top_k=5):
                new_job_list.append(doc.split("\t")[0])
            for idx, score, doc in bm25_zh_other_job.search(query, top_k=5):
                new_job_list.append(doc.split("\t")[0])
            system_prompt = "\n".join(new_job_list) + "\n" + """
            你是一名助理，现在老板提出了需求，你现在根据他给到的需求，根据上述职业，找到最适合这一任务职业的人。
            对话规则：
            1.只输出1名职业名称。
            2.语言简短口语化，不要长篇大论。
            """
            res = call_ai(query, system_prompt, use_local=use_local)
            if res in new_job_list:
                job_list.append(res)
    job_list = list(set(job_list))
    return json.dumps(job_list)
if __name__ == '__main__':
    print(search_job("帮我敲下这代码"))