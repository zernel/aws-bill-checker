import boto3
import datetime
from dateutil.relativedelta import relativedelta
import sys
import os
import logging
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- 配置 ---
# 定义异常阈值 (从环境变量读取，未配置时使用默认值)
THRESHOLD_DOLLAR = float(os.environ.get('THRESHOLD_DOLLAR', '50.0'))
THRESHOLD_PERCENT = float(os.environ.get('THRESHOLD_PERCENT', '25.0'))
THRESHOLD_PERCENT_MIN_COST = float(os.environ.get('THRESHOLD_PERCENT_MIN_COST', '10.0'))

# 货币符号 (从环境变量读取，默认为 $)
CURRENCY_SYMBOL = os.environ.get('CURRENCY_SYMBOL', '$')

# 语言设置 (从环境变量读取，默认为 CN)
LANGUAGE = os.environ.get('LANGUAGE', 'CN').upper()

# Notification Webhook URLs (从环境变量读取)
FEISHU_WEBHOOK_URL = os.environ.get('FEISHU_WEBHOOK_URL', '')
MATTERMOST_WEBHOOK_URL = os.environ.get('MATTERMOST_WEBHOOK_URL', '')

# 日志配置
LOG_DIR = Path(__file__).parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"aws_bill_checker_{datetime.date.today().strftime('%Y%m')}.log"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 语言字符串定义
LANG_STRINGS = {
    'CN': {
        'error_title': '❌ AWS 账单检查失败',
        'error_content': '**错误**: 无法获取 {month} 的账单数据\n\n请检查 AWS 凭证和 IAM 权限 (需要 ce:GetCostAndUsage)',
        'warning_title': '⚠️ AWS 账单检查警告',
        'warning_content': '未能获取到任何账单数据',
        'anomaly_title': '⚠️ AWS 账单检查: 发现异常',
        'normal_title': '✅ AWS 账单检查: 一切正常',
        'bill_period': '📊 **账单周期**: {prev_month} vs {last_month}',
        'total_cost': '**💰 总费用**',
        'change': '变化',
        'anomalies_found': '**⚠️ 发现 {count} 个异常项** (阈值: {currency}{threshold_dollar} 或 {threshold_percent}%):',
        'no_anomalies': '✅ **未发现明显异常增长的服务**',
        'threshold_info': '   (阈值: {currency}{threshold_dollar} 或 {threshold_percent}%)',
        'service_change': '   - 变化: {currency}{diff:+,.2f} ({percent:+.2f}%)'
    },
    'EN': {
        'error_title': '❌ AWS Bill Check Failed',
        'error_content': '**Error**: Failed to retrieve bill data for {month}\n\nPlease check AWS credentials and IAM permissions (requires ce:GetCostAndUsage)',
        'warning_title': '⚠️ AWS Bill Check Warning',
        'warning_content': 'No bill data retrieved for both months',
        'anomaly_title': '⚠️ AWS Bill Check: Anomalies Detected',
        'normal_title': '✅ AWS Bill Check: All Normal',
        'bill_period': '📊 **Billing Period**: {prev_month} vs {last_month}',
        'total_cost': '**💰 Total Cost**',
        'change': 'Change',
        'anomalies_found': '**⚠️ Found {count} anomaly/anomalies** (threshold: {currency}{threshold_dollar} or {threshold_percent}%):',
        'no_anomalies': '✅ **No significant cost increases detected**',
        'threshold_info': '   (threshold: {currency}{threshold_dollar} or {threshold_percent}%)',
        'service_change': '   - Change: {currency}{diff:+,.2f} ({percent:+.2f}%)'
    }
}

# 获取当前语言的字符串
def get_text(key, **kwargs):
    """Get localized text string"""
    return LANG_STRINGS.get(LANGUAGE, LANG_STRINGS['CN'])[key].format(**kwargs)

# -------------

def send_feishu_notification(title, content, color="green"):
    """Send notification to Feishu via webhook using card message
    
    Args:
        title: Message title
        content: Message content (can include markdown)
        color: Card color - "green" for normal, "red" for error, "orange" for warning
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not FEISHU_WEBHOOK_URL:
        logger.debug("FEISHU_WEBHOOK_URL not configured, skipping Feishu notification")
        return False
    
    # Feishu card message template
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "content": title,
                    "tag": "plain_text"
                },
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": content,
                        "tag": "lark_md"
                    }
                }
            ]
        }
    }
    
    try:
        response = requests.post(
            FEISHU_WEBHOOK_URL,
            json=card,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        if result.get('StatusCode') == 0 or result.get('code') == 0:
            logger.info("Feishu notification sent successfully")
            return True
        else:
            logger.error(f"Feishu notification failed: {result}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Feishu notification: {e}", exc_info=True)
        return False

def send_mattermost_notification(title, content, color="good"):
    """Send notification to Mattermost via webhook
    
    Args:
        title: Message title
        content: Message content (markdown supported)
        color: Attachment color - "good" for normal, "danger" for error, "warning" for warning
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not MATTERMOST_WEBHOOK_URL:
        logger.debug("MATTERMOST_WEBHOOK_URL not configured, skipping Mattermost notification")
        return False
    
    # Map color names
    color_map = {
        "green": "good",
        "red": "danger",
        "orange": "warning"
    }
    mattermost_color = color_map.get(color, color)
    
    # Mattermost message payload
    payload = {
        "username": "AWS Bill Checker",
        "icon_emoji": ":chart_with_upwards_trend:",
        "attachments": [
            {
                "color": mattermost_color,
                "title": title,
                "text": content,
                "mrkdwn_in": ["text"]
            }
        ]
    }
    
    try:
        response = requests.post(
            MATTERMOST_WEBHOOK_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        
        if response.status_code == 200:
            logger.info("Mattermost notification sent successfully")
            return True
        else:
            logger.error(f"Mattermost notification failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Mattermost notification: {e}", exc_info=True)
        return False

def send_notification(title, content, color="green"):
    """Send notification to configured platforms (Feishu and/or Mattermost)
    
    Args:
        title: Message title
        content: Message content
        color: Color indicator - "green" for normal, "red" for error, "orange" for warning
    
    Returns:
        bool: True if at least one notification was sent successfully
    """
    if not FEISHU_WEBHOOK_URL and not MATTERMOST_WEBHOOK_URL:
        logger.warning("No notification webhook configured (FEISHU_WEBHOOK_URL or MATTERMOST_WEBHOOK_URL)")
        return False
    
    success = False
    
    # Send to Feishu if configured
    if FEISHU_WEBHOOK_URL:
        if send_feishu_notification(title, content, color):
            success = True
    
    # Send to Mattermost if configured
    if MATTERMOST_WEBHOOK_URL:
        if send_mattermost_notification(title, content, color):
            success = True
    
    return success

def get_monthly_costs(start_date, end_date):
    """使用 Cost Explorer API 查询指定时间段内按服务分类的成本"""
    client = boto3.client('ce')
    try:
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        )
        return response
    except Exception as e:
        logger.error(f"Failed to call AWS Cost Explorer API: {e}", exc_info=True)
        return None

def parse_costs_to_dict(response):
    """将 Cost Explorer 的 API 响应解析为 {服务名: 金额} 的字典"""
    costs = {}
    if not response or not response.get('ResultsByTime'):
        return costs

    # API 可能返回空组，即使有总成本
    groups = response['ResultsByTime'][0].get('Groups', [])
    for group in groups:
        service_name = group['Keys'][0]
        cost = float(group['Metrics']['UnblendedCost']['Amount'])
        costs[service_name] = cost
    return costs

def main():
    logger.info("=" * 80)
    logger.info("AWS Bill Checker started")
    logger.info("=" * 80)
    
    # 1. 计算日期
    today = datetime.date.today()
    # 上个月的结束日期 (即本月第一天)
    last_month_end_dt = today.replace(day=1)
    # 上个月的开始日期
    last_month_start_dt = last_month_end_dt - relativedelta(months=1)
    # 上上个月的开始日期
    prev_month_start_dt = last_month_end_dt - relativedelta(months=2)

    # 格式化为 YYYY-MM-DD 字符串
    last_month_start = last_month_start_dt.strftime('%Y-%m-%d')
    last_month_end = last_month_end_dt.strftime('%Y-%m-%d')
    prev_month_start = prev_month_start_dt.strftime('%Y-%m-%d')
    prev_month_end = last_month_start # 上上月的结束 = 上月的开始
    
    # 用于显示的月份名称
    prev_month_name = prev_month_start_dt.strftime('%Y-%m')
    last_month_name = last_month_start_dt.strftime('%Y-%m')

    # 2. API 调用
    logger.info(f"Querying AWS bills for {prev_month_name} and {last_month_name}")
    logger.info(f"Previous month: {prev_month_start} to {prev_month_end}")
    
    prev_month_data = get_monthly_costs(prev_month_start, prev_month_end)
    prev_costs = parse_costs_to_dict(prev_month_data)
    
    if prev_month_data is None:
        error_msg = f"Failed to retrieve AWS bill data for {prev_month_name}"
        logger.error(error_msg)
        send_notification(
            title=get_text('error_title'),
            content=get_text('error_content', month=prev_month_name),
            color="red"
        )
        return

    logger.info(f"Last month: {last_month_start} to {last_month_end}")
    last_month_data = get_monthly_costs(last_month_start, last_month_end)
    last_costs = parse_costs_to_dict(last_month_data)
    
    if last_month_data is None:
        error_msg = f"Failed to retrieve AWS bill data for {last_month_name}"
        logger.error(error_msg)
        send_notification(
            title=get_text('error_title'),
            content=get_text('error_content', month=last_month_name),
            color="red"
        )
        return

    if not prev_costs and not last_costs:
        logger.warning("No bill data retrieved for both months")
        send_notification(
            title=get_text('warning_title'),
            content=get_text('warning_content'),
            color="orange"
        )
        return

    # 3. 数据处理和对比
    all_services = set(prev_costs.keys()) | set(last_costs.keys())
    report_lines = []
    anomalies = []

    total_prev = 0.0
    total_last = 0.0

    for service in sorted(list(all_services)):
        prev = prev_costs.get(service, 0.0)
        last = last_costs.get(service, 0.0)
        diff = last - prev

        percent = 0.0
        if prev > 0.001: # 避免除零
            percent = (diff / prev) * 100.0
        elif last > 0.001:
            percent = 100.0 # 新增服务

        total_prev += prev
        total_last += last

        report_lines.append((service, prev, last, diff, percent))

        # 检查异常
        if diff > THRESHOLD_DOLLAR or (percent > THRESHOLD_PERCENT and last > THRESHOLD_PERCENT_MIN_COST):
            anomalies.append({
                'service': service,
                'prev': prev,
                'last': last,
                'diff': diff,
                'percent': percent
            })

    # 4. 记录详细报告到日志
    logger.info("-" * 105)
    logger.info(f"AWS Bill Comparison Report: {prev_month_name} vs {last_month_name}")
    logger.info("-" * 105)
    logger.info(f"{'Service':<45} | {'Prev Month ($)':<15} | {'Last Month ($)':<15} | {'Change ($)':<15} | {'Change (%)':<10}")
    logger.info("-" * 105)

    for line in report_lines:
        service, prev, last, diff, percent = line
        logger.info(f"{service:<45} | {prev:<15.2f} | {last:<15.2f} | {diff:<15.2f} | {percent:<10.2f}%")

    # 计算总计
    total_diff = total_last - total_prev
    total_percent = 0.0
    if total_prev > 0.001:
        total_percent = (total_diff / total_prev) * 100.0
    elif total_last > 0.001:
        total_percent = 100.0

    logger.info("-" * 105)
    logger.info(f"{'TOTAL':<45} | {total_prev:<15.2f} | {total_last:<15.2f} | {total_diff:<15.2f} | {total_percent:<10.2f}%")
    logger.info("-" * 105)

    # 5. 发送飞书通知（总览 + 异常项）
    if anomalies:
        # 有异常情况
        logger.warning(f"Found {len(anomalies)} anomaly/anomalies")
        for anomaly in anomalies:
            logger.warning(f"  - {anomaly['service']}: ${anomaly['diff']:,.2f} ({anomaly['percent']:.2f}%)")
        
        # 构建通知消息内容
        content_lines = [
            get_text('bill_period', prev_month=prev_month_name, last_month=last_month_name),
            "",
            get_text('total_cost'),
            f"- {prev_month_name}: {CURRENCY_SYMBOL}{total_prev:,.2f}",
            f"- {last_month_name}: {CURRENCY_SYMBOL}{total_last:,.2f}",
            f"- {get_text('change')}: {CURRENCY_SYMBOL}{total_diff:,.2f} ({total_percent:+.2f}%)",
            "",
            get_text('anomalies_found', count=len(anomalies), currency=CURRENCY_SYMBOL, threshold_dollar=THRESHOLD_DOLLAR, threshold_percent=THRESHOLD_PERCENT),
        ]
        
        for anomaly in anomalies:
            content_lines.append(
                f"🔸 **{anomaly['service']}**\n"
                f"   - {prev_month_name}: {CURRENCY_SYMBOL}{anomaly['prev']:,.2f}\n"
                f"   - {last_month_name}: {CURRENCY_SYMBOL}{anomaly['last']:,.2f}\n"
                f"{get_text('service_change', currency=CURRENCY_SYMBOL, diff=anomaly['diff'], percent=anomaly['percent'])}"
            )
        
        send_notification(
            title=get_text('anomaly_title'),
            content="\n".join(content_lines),
            color="orange"
        )
    else:
        # 一切正常
        logger.info("No anomalies detected")
        
        content_lines = [
            get_text('bill_period', prev_month=prev_month_name, last_month=last_month_name),
            "",
            get_text('total_cost'),
            f"- {prev_month_name}: {CURRENCY_SYMBOL}{total_prev:,.2f}",
            f"- {last_month_name}: {CURRENCY_SYMBOL}{total_last:,.2f}",
            f"- {get_text('change')}: {CURRENCY_SYMBOL}{total_diff:,.2f} ({total_percent:+.2f}%)",
            "",
            get_text('no_anomalies'),
            get_text('threshold_info', currency=CURRENCY_SYMBOL, threshold_dollar=THRESHOLD_DOLLAR, threshold_percent=THRESHOLD_PERCENT)
        ]
        
        send_notification(
            title=get_text('normal_title'),
            content="\n".join(content_lines),
            color="green"
        )
    
    logger.info("AWS Bill Checker completed successfully")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()
