import re

def add_to_ts(filepath, new_content):
    with open(filepath, 'r') as f:
        content = f.read()
    
    last_brace_idx = content.rfind('}')
    if last_brace_idx != -1:
        updated = content[:last_brace_idx] + new_content + "\n" + content[last_brace_idx:]
        with open(filepath, 'w') as f:
            f.write(updated)

zh_content = """
  traceStep: {
    input: '输入',
    output: '输出',
    tool: '工具',
    copied: '已复制',
    copy: '复制'
  },
"""

en_content = """
  traceStep: {
    input: 'Input',
    output: 'Output',
    tool: 'Tool',
    copied: 'Copied',
    copy: 'Copy'
  },
"""

add_to_ts('src/i18n/zh.ts', zh_content)
add_to_ts('src/i18n/en.ts', en_content)

# Update AppLoading.vue
with open('src/components/AppLoading.vue', 'r') as f:
    app_loading = f.read()
app_loading = app_loading.replace('加载中...', '{{ $t(\'common.loading\') }}')
with open('src/components/AppLoading.vue', 'w') as f:
    f.write(app_loading)

# Update TraceStepCard.vue
with open('src/components/TraceStepCard.vue', 'r') as f:
    trace_card = f.read()

trace_card = trace_card.replace(">输入</div>", ">{{ $t('traceStep.input') }}</div>")
trace_card = trace_card.replace(">输出</div>", ">{{ $t('traceStep.output') }}</div>")
trace_card = trace_card.replace("'工具'", "t('traceStep.tool')")
trace_card = trace_card.replace("'已复制' : '复制'", "t('traceStep.copied') : t('traceStep.copy')")
trace_card = trace_card.replace("`输入\\n${formattedInput.value}`", "`${t('traceStep.input')}\\n${formattedInput.value}`")
trace_card = trace_card.replace("`输出\\n${effectiveOutput.value}`", "`${t('traceStep.output')}\\n${effectiveOutput.value}`")

with open('src/components/TraceStepCard.vue', 'w') as f:
    f.write(trace_card)

