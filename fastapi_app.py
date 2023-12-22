#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    :   fastapi_app.py
@Time    :   2023/12/22 23:08:32
@Author  :   lvguanjun
@Desc    :   fastapi_app.py
"""

import asyncio
import re
from hashlib import sha256

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from api.base import Account, Chaoxing
from api.logger import logger

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

# 存储后台任务的全局字典，键为账号密码的组合
background_tasks = {}


def check_study(chaoxing: Chaoxing, course_list):
    _login_state = chaoxing.login()
    if not _login_state["status"]:
        return False, "账号登录失败"
    # 获取所有的课程列表
    all_course = chaoxing.get_course_list()
    course_task = []
    for course in all_course:
        if course["courseId"] in course_list:
            course_task.append(course)
    if not course_task:
        return False, "没有选择任何有效课程"
    return True, course_task


async def async_study(chaoxing: Chaoxing, course_task: list, speed: int):
    try:
        for course in course_task:
            # 获取当前课程的所有章节
            point_list = chaoxing.get_course_point(
                course["courseId"], course["clazzId"], course["cpi"]
            )
            for point in point_list["points"]:
                # 获取当前章节的所有任务点
                jobs = []
                job_info = None
                try:
                    jobs, job_info = chaoxing.get_job_list(
                        course["clazzId"],
                        course["courseId"],
                        course["cpi"],
                        point["id"],
                    )
                except:
                    logger.warning(f"跳过错误章节 -> {point['title']}")

                # 可能存在章节无任何内容的情况
                if not jobs:
                    continue
                # 遍历所有任务点
                for job in jobs:
                    # 视频任务
                    if job["type"] == "video":
                        logger.trace(
                            f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}"
                        )
                        await chaoxing.async_study_video(
                            course, job, job_info, _speed=speed
                        )
                    # 文档任务
                    elif job["type"] == "document":
                        logger.trace(
                            f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}"
                        )
                        chaoxing.study_document(course, job)
                    # 测验任务
                    elif job["type"] == "workid":
                        logger.trace(f"识别到测验任务, 任务章节: {course['title']}")
                        pass
    except asyncio.CancelledError:
        logger.warning("任务被取消")
    except Exception as e:
        logger.error(f"任务异常: {e}")
    finally:
        logger.info("任务结束")
        background_tasks.pop(
            generate_task_key(chaoxing.account.username, chaoxing.account.password),
            None,
        )


# 根据账号和密码生成任务标识符
def generate_task_key(username: str, password: str) -> str:
    return sha256(f"{username}:{password}".encode("utf-8")).hexdigest()


class AccountModel(BaseModel):
    username: str
    password: str

    @field_validator("username")
    def check_phone(cls, v):
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式错误")
        return v


class StudyTask(AccountModel):
    course_list: list[str]
    speed: int = 1

    @field_validator("speed")
    def validate_speed(cls, v):
        if v < 1 or v > 2:
            raise ValueError("倍速最高为2倍速")
        return v

    @field_validator("course_list")
    def course_list_not_empty(cls, v):
        if not v:
            raise ValueError("课程列表不能为空")
        return v


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@app.post("/start-study")
async def start_study(task: StudyTask):
    task_key = generate_task_key(task.username, task.password)

    if task_key in background_tasks:
        raise HTTPException(status_code=400, detail="已经有相同账号密码的任务正在运行")

    account = Account(task.username, task.password)
    # 实例化超星API
    chaoxing = Chaoxing(account=account)

    is_valid, course_task_or_msg = check_study(chaoxing, task.course_list)
    if not is_valid:
        raise HTTPException(status_code=400, detail=course_task_or_msg)

    # 创建并启动新的异步任务
    task_instance = asyncio.create_task(
        async_study(chaoxing, course_task_or_msg, task.speed)
    )
    background_tasks[task_key] = task_instance

    return {"detail": "后台任务已启动"}


@app.post("/cancel-study")
async def cancel_study(task: AccountModel):
    task_key = generate_task_key(task.username, task.password)
    task_instance = background_tasks.get(task_key)

    if not task_instance:
        raise HTTPException(status_code=404, detail="没有找到对应的任务")

    task_instance.cancel()
    background_tasks.pop(task_key, None)
    logger.info(f"取消任务成功: {task_key}")

    return {"detail": "后台任务已取消"}


@app.get("/study-tasks")
async def get_study_tasks():
    return {
        "tasks": list(background_tasks.keys()),
        "count": len(background_tasks),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=8080)
