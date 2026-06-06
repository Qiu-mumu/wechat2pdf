#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章转PDF - Vercel Serverless API入口
从 app.py 导入所有功能，适配Vercel平台
"""

import os
import sys
import io

# Vercel Serverless 环境适配
# Vercel使用 /tmp 作为临时目录
TEMP_DIR = '/tmp/wechat2pdf'
os.makedirs(TEMP_DIR, exist_ok=True)

# 确保能找到模板文件
# Vercel部署时，模板在 api/templates/ 下
template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
if os.path.exists(template_dir):
    # Vercel环境
    pass
else:
    # 本地开发环境
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')

# 将父目录加入路径，以便导入 app 模块
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 导入主应用
from app import app

# 覆盖模板路径
app.template_folder = template_dir

# Vercel Serverless 导出
# Vercel需要从 api/index.py 导出 app
module = type(sys)('module')
module.app = app
