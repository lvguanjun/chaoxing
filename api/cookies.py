# -*- coding: utf-8 -*-
import os.path
import pickle

from api.config import GlobalConst as gc

cookies_map = {}


def save_cookies(username, _session):
    cookies_map[username] = _session.cookies


def use_cookies(username):
    cookies = cookies_map.get(username)
    return cookies
