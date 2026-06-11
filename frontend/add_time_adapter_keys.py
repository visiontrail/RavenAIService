import re

def add_to_ts(filepath, new_content):
    with open(filepath, 'r') as f:
        content = f.read()
    
    last_brace_idx = content.rfind('}')
    if last_brace_idx != -1:
        updated = content[:last_brace_idx] + new_content + '\n' + content[last_brace_idx:]
        with open(filepath, 'w') as f:
            f.write(updated)

zh_content = """
  time: {
    justNow: '刚刚',
    secondsAgo: '{seconds}秒前',
    minutesAgo: '{minutes}分钟前',
    hoursAgo: '{hours}小时前',
    daysAgo: '{days}天前'
  },
  adapter: {
    copied: '已复制',
    copy: '复制',
    missingId: '缺少分析ID',
    missingQuery: '缺少查询内容',
    missingTimestamp: '缺少时间戳',
    missingContent: '缺少分析结果内容',
    analysisQueryFallback: '日志分析',
    planCompleted: '执行计划已完成',
    stepFallback: '步骤 {index}',
    reasoningFallback: '执行分析步骤',
    approachFallback: '使用工具进行分析',
    expectedFallback: '获取分析结果',
    analysisCompleted: '分析已完成',
    dataAnalysisFallback: '数据分析',
    dataProcessed: '数据处理完成',
    processedRawData: '已处理原始数据',
    checkDataFormat: '请检查数据格式',
    useStandardOutput: '考虑使用标准化输出',
    analysisFailedQuery: '分析失败',
    analysisFailedContent: '分析过程中出现错误',
    errorInfoMsg: '**错误信息:** {msg}\\n\\n**原始数据:**\\n```json\\n{data}\\n```',
    contactSupport: '联系技术支持',
    noSummaryInfo: '无摘要信息'
  },
"""

en_content = """
  time: {
    justNow: 'Just now',
    secondsAgo: '{seconds}s ago',
    minutesAgo: '{minutes}m ago',
    hoursAgo: '{hours}h ago',
    daysAgo: '{days}d ago'
  },
  adapter: {
    copied: 'Copied',
    copy: 'Copy',
    missingId: 'Missing analysis ID',
    missingQuery: 'Missing query content',
    missingTimestamp: 'Missing timestamp',
    missingContent: 'Missing analysis result content',
    analysisQueryFallback: 'Log analysis',
    planCompleted: 'Execution plan completed',
    stepFallback: 'Step {index}',
    reasoningFallback: 'Execute analysis step',
    approachFallback: 'Analyze using tools',
    expectedFallback: 'Get analysis result',
    analysisCompleted: 'Analysis completed',
    dataAnalysisFallback: 'Data analysis',
    dataProcessed: 'Data processing complete',
    processedRawData: 'Raw data processed',
    checkDataFormat: 'Please check data format',
    useStandardOutput: 'Consider standard output',
    analysisFailedQuery: 'Analysis failed',
    analysisFailedContent: 'An error occurred during analysis',
    errorInfoMsg: '**Error details:** {msg}\\n\\n**Raw data:**\\n```json\\n{data}\\n```',
    contactSupport: 'Contact technical support',
    noSummaryInfo: 'No summary information'
  },
"""

add_to_ts('src/i18n/zh.ts', zh_content)
add_to_ts('src/i18n/en.ts', en_content)
