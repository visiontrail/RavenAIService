# AI分析结果数据结构设计

## 标准化输出格式

### 1. 主要数据结构

```typescript
interface AIAnalysisResult {
  // 基础信息
  id: string
  query: string
  status: 'processing' | 'completed' | 'failed'
  timestamp: string
  
  // 执行计划
  plan: {
    content: string           // 原始计划内容（markdown格式）
    steps: PlanStep[]        // 解析后的步骤列表
    total_steps: number      // 总步骤数
    completed_steps: number  // 已完成步骤数
  }
  
  // 执行过程
  acts: ActResult[]
  
  // 最终结果
  final_result: {
    summary: string          // 简要总结
    content: string          // 详细分析结果（markdown格式）
    confidence: number       // 置信度 (0-1)
    recommendations: string[] // 建议列表
  }
  
  // 元数据
  metadata: {
    execution_time: number   // 执行时间（秒）
    model_used: string      // 使用的模型
    tokens_used: number     // 消耗的token数
  }
}

interface PlanStep {
  id: string
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  order: number
}

interface ActResult {
  step_id: string
  title: string
  status: 'completed' | 'failed'
  
  // 思考过程
  thought: {
    reasoning: string        // 推理过程
    approach: string        // 采用的方法
    expected_outcome: string // 预期结果
  }
  
  // 执行结果
  execution: {
    tool_used: string       // 使用的工具
    raw_output: string      // 原始输出
    processed_output: string // 处理后的输出（markdown格式）
    success: boolean        // 是否成功
    error_message?: string  // 错误信息（如果有）
  }
  
  // 总结
  summary: string
  timestamp: string
}
```

### 2. Markdown格式规范

#### 2.1 最终结果格式
```markdown
# 日志分析结果

## 📊 执行摘要
[简要总结]

## 🔍 详细分析
[详细分析内容，支持表格、列表等]

### 关键发现
- 发现1
- 发现2

### 问题诊断
| 问题类型 | 严重程度 | 描述 | 建议 |
|---------|---------|------|------|
| 错误 | 高 | 描述 | 建议 |

## 💡 建议措施
1. 建议1
2. 建议2

## 📈 统计信息
[相关统计图表或数据]
```

#### 2.2 计划格式
```markdown
# 分析计划

## 步骤概览
1. **步骤1标题** - 步骤描述
2. **步骤2标题** - 步骤描述
3. **步骤3标题** - 步骤描述

## 预期目标
[描述分析目标和预期结果]
```

#### 2.3 执行过程格式
```markdown
## 步骤X: [步骤标题]

### 🤔 思考过程
[推理和方法选择]

### ⚙️ 执行过程
[具体执行步骤和使用的工具]

### 📋 执行结果
[结果输出，支持代码块、表格等]

### 📝 小结
[本步骤的总结]
```

### 3. 前端展示层次

```
┌─ 主结果区域 (大字号，高可读性)
│  ├─ 执行摘要
│  ├─ 关键发现
│  └─ 建议措施
│
├─ 执行计划区域 (中等字号)
│  ├─ 步骤进度条
│  └─ 步骤列表
│
└─ 详细过程区域 (小字号，可折叠)
   ├─ 步骤1 [可折叠]
   │  ├─ 思考过程 [可折叠]
   │  ├─ 执行过程 [可折叠]
   │  └─ 执行结果 [可折叠]
   ├─ 步骤2 [可折叠]
   └─ ...
```

### 4. 交互设计规范

#### 4.1 折叠控件
- 使用统一的展开/收起图标
- 平滑的旋转动画 (0.3s ease-in-out)
- 内容区域的滑动展开效果

#### 4.2 加载状态
- 骨架屏加载效果
- 进度条显示执行进度
- 实时更新执行状态

#### 4.3 响应式设计
- 移动端优化的触控体验
- 自适应字体大小
- 合理的间距和布局比例

### 5. 无障碍访问
- 语义化HTML结构
- 适当的ARIA标签
- 键盘导航支持
- 高对比度模式支持