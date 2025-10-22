import boto3
import datetime
from dateutil.relativedelta import relativedelta
import sys

# --- 配置 ---
# 定义异常阈值
THRESHOLD_DOLLAR = 50.0
THRESHOLD_PERCENT = 25.0
THRESHOLD_PERCENT_MIN_COST = 10.0 # 忽略从 $0.1 -> $0.2 这种增长
# -------------

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
        print(f"错误: 调用 AWS Cost Explorer API 失败: {e}", file=sys.stderr)
        print("请检查您的 AWS 凭证和 IAM 权限 (需要 ce:GetCostAndUsage)。", file=sys.stderr)
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

    # 2. API 调用
    print(f"正在查询 [上上月] 账单 ({prev_month_start} 到 {prev_month_end})...")
    prev_month_data = get_monthly_costs(prev_month_start, prev_month_end)
    prev_costs = parse_costs_to_dict(prev_month_data)

    print(f"正在查询 [上个月] 账单 ({last_month_start} 到 {last_month_end})...")
    last_month_data = get_monthly_costs(last_month_start, last_month_end)
    last_costs = parse_costs_to_dict(last_month_data)

    if not prev_costs and not last_costs:
        print("未能获取到任何账单数据。")
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
            anomalies.append(f"[!!] {service:<45} | 增长: ${diff:,.2f} ({percent:.2f}%)")

    # 4. 打印报告
    print("\n" + f"--- AWS 账单对比 ({prev_month_start} vs {last_month_start}) ---")
    print("-" * 105)
    print(f"{'服务 (Service)':<45} | {'上上月 ($)':<15} | {'上个月 ($)':<15} | {'变化 ($)':<15} | {'变化 (%)':<10}")
    print("-" * 105)

    for line in report_lines:
        service, prev, last, diff, percent = line
        print(f"{service:<45} | {prev:<15.2f} | {last:<15.2f} | {diff:<15.2f} | {percent:<10.2f}%")

    # 打印总计
    total_diff = total_last - total_prev
    total_percent = 0.0
    if total_prev > 0.001:
        total_percent = (total_diff / total_prev) * 100.0
    elif total_last > 0.001:
        total_percent = 100.0

    print("-" * 105)
    print(f"{'总计 (TOTAL)':<45} | {total_prev:<15.2f} | {total_last:<15.2f} | {total_diff:<15.2f} | {total_percent:<10.2f}%")

    # 打印异常
    print("\n" + f"--- 异常情况高亮 (阈值: ${THRESHOLD_DOLLAR} 或 {THRESHOLD_PERCENT}%) ---")
    if anomalies:
        for anomaly in anomalies:
            print(anomaly)
    else:
        print("未发现明显异常增长的服务。")

if __name__ == "__main__":
    main()
