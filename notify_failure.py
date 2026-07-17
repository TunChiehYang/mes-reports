#!/usr/bin/env python3
"""定时任务失败邮件通知"""
import sys, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

TASK_NAME = sys.argv[1] if len(sys.argv) > 1 else "未知任务"
ERROR_MSG = sys.argv[2] if len(sys.argv) > 2 else "无错误信息"

SMTP_HOST = "mail.chiachang.com"
SMTP_PORT = 465
SENDER = "b-mes@chiachang.com"

RECIPIENTS = ["prima.yang@chiachang.com"]

msg = MIMEMultipart()
msg['From'] = f"MES系统 <{SENDER}>"
msg['To'] = ', '.join(RECIPIENTS)
msg['Subject'] = Header(f'[MES异常] {TASK_NAME} 执行失败', 'utf-8')

body = f"""定时任务执行异常通知

任务名称: {TASK_NAME}
错误信息: {ERROR_MSG}

请检查相关脚本和数据源。

此致
MES系统 · 自动发送
"""
msg.attach(MIMEText(body, 'plain', 'utf-8'))

server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
server.login("b-mes", "gmo@1001")
server.sendmail(SENDER, RECIPIENTS, msg.as_string())
server.quit()
print(f"已发送失败通知: {TASK_NAME}")
