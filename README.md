# AWS Bill Checker

自动检查 AWS 账单变化并发送飞书通知的工具。

## Features

- 🔍 **自动对比分析**: 对比上个月和上上个月的 AWS 账单，按服务分类统计
- 📊 **异常检测**: 自动识别费用异常增长的服务（金额或百分比阈值）
- 🔔 **飞书通知**: 使用卡片消息格式发送通知，清晰区分正常/异常状态
- 📝 **详细日志**: 记录完整的对比报告和执行日志
- ⏰ **定时执行**: 每月 5 日自动运行（确保上月账单已 Finalized）

## System Requirements

- **OS**: Ubuntu 24.04 LTS (或其他 Linux 发行版)
- **Python**: 3.8+
- **AWS Account**: 需要有效的 AWS 凭证和 Cost Explorer 权限

## Installation

### 1. Clone the repository

```bash
cd /opt  # 或其他你想部署的目录
git clone <your-repo-url> aws-bill-checker
cd aws-bill-checker
```

### 2. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

或使用虚拟环境（推荐）：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure AWS credentials

确保已配置 AWS 凭证文件 `~/.aws/credentials`：

```ini
[default]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
region = us-east-1  # 或你的默认区域
```

**所需 IAM 权限**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage"
      ],
      "Resource": "*"
    }
  ]
}
```

### 4. Configure Feishu Webhook

设置环境变量 `FEISHU_WEBHOOK_URL`：

```bash
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
```

为了持久化配置，建议添加到 cron 任务的环境变量中（见下文）。

**获取飞书 Webhook URL**:
1. 在飞书群聊中，点击群设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 设置机器人名称和描述
3. 复制生成的 Webhook URL

## Configuration

### Threshold Settings

在 `main.py` 中可以调整异常检测的阈值：

```python
THRESHOLD_DOLLAR = 50.0              # 费用增长超过 $50
THRESHOLD_PERCENT = 25.0             # 费用增长超过 25%
THRESHOLD_PERCENT_MIN_COST = 10.0   # 百分比阈值的最小金额（避免 $0.1 -> $0.2 被标记为异常）
```

## Setup Cron Job

### 方式一：使用 crontab（推荐用于虚拟环境）

```bash
crontab -e
```

添加以下内容（每月 5 日上午 9:00 UTC 执行）：

```cron
# AWS Bill Checker - Run on 5th of every month at 9:00 AM UTC
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx

0 9 5 * * /opt/aws-bill-checker/venv/bin/python /opt/aws-bill-checker/main.py >> /opt/aws-bill-checker/logs/cron.log 2>&1
```

**注意事项**:
- 替换 `FEISHU_WEBHOOK_URL` 为你的实际 Webhook URL
- 如果使用虚拟环境，使用虚拟环境中的 python 路径
- 如果使用系统 Python，路径改为 `/usr/bin/python3`
- 确保路径都是绝对路径

### 方式二：使用系统 Python（不使用虚拟环境）

```cron
# AWS Bill Checker - Run on 5th of every month at 9:00 AM UTC
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx

0 9 5 * * cd /opt/aws-bill-checker && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

### 验证 Cron 配置

```bash
# 查看当前 cron 任务
crontab -l

# 检查 cron 服务状态
sudo systemctl status cron

# 查看 cron 日志
sudo tail -f /var/log/syslog | grep CRON
```

## Manual Testing

手动测试脚本运行：

```bash
cd /opt/aws-bill-checker

# 如果使用虚拟环境
source venv/bin/activate

# 设置环境变量并运行
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
python main.py
```

查看执行日志：

```bash
tail -f logs/aws_bill_checker_*.log
```

## Log Files

日志文件存储在 `logs/` 目录下：

- `aws_bill_checker_YYYYMM.log` - 每月的详细执行日志
- `cron.log` - cron 任务的标准输出日志

日志包含：
- 详细的账单对比表格（所有服务）
- 异常检测结果
- API 调用状态
- 飞书通知发送状态

## Feishu Notification Format

### 正常情况（绿色卡片）

```
✅ AWS 账单检查 - 一切正常
━━━━━━━━━━━━━━━━━━━━━━━
📊 账单周期: 2025-08 vs 2025-09

💰 总费用
- 2025-08: $1,234.56
- 2025-09: $1,198.23
- 变化: -$36.33 (-2.94%)

✅ 未发现明显异常增长的服务
   (阈值: $50 或 25%)
```

### 异常情况（橙色卡片）

```
⚠️ AWS 账单检查 - 发现异常
━━━━━━━━━━━━━━━━━━━━━━━
📊 账单周期: 2025-08 vs 2025-09

💰 总费用
- 2025-08: $1,234.56
- 2025-09: $1,567.89
- 变化: +$333.33 (+27.00%)

⚠️ 发现 2 个异常项 (阈值: $50 或 25%):

🔸 Amazon EC2
   - 2025-08: $500.00
   - 2025-09: $750.00
   - 变化: +$250.00 (+50.00%)

🔸 Amazon S3
   - 2025-08: $100.00
   - 2025-09: $180.00
   - 变化: +$80.00 (+80.00%)
```

## Troubleshooting

### AWS API 调用失败

**症状**: 收到红色飞书通知 "AWS 账单检查失败"

**可能原因**:
1. AWS 凭证未配置或已过期
2. IAM 权限不足（缺少 `ce:GetCostAndUsage` 权限）
3. Cost Explorer API 未启用（首次使用需要在 AWS 控制台启用）

**解决方法**:
```bash
# 验证 AWS 凭证
aws sts get-caller-identity

# 检查 Cost Explorer 权限
aws ce get-cost-and-usage --time-period Start=2025-01-01,End=2025-01-31 --granularity=MONTHLY --metrics=UnblendedCost
```

### 飞书通知未收到

**症状**: 脚本执行成功但未收到飞书通知

**检查步骤**:
1. 查看日志文件，确认是否有发送失败的错误信息
2. 验证 `FEISHU_WEBHOOK_URL` 环境变量是否正确设置
3. 测试 Webhook URL 是否有效：
   ```bash
   curl -X POST \
     -H 'Content-Type: application/json' \
     -d '{"msg_type":"text","content":{"text":"test"}}' \
     YOUR_WEBHOOK_URL
   ```

### Cron 任务未执行

**检查步骤**:
1. 确认 cron 服务正在运行: `sudo systemctl status cron`
2. 检查 cron 日志: `sudo grep CRON /var/log/syslog`
3. 确认 Python 路径正确: `which python3`
4. 手动执行脚本测试

## License

MIT