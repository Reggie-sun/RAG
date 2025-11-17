RAG系统混合检索增强与问题类型识别功能实现

## 问题背景
当前RAG系统需要增强混合检索功能，实现针对不同问题类型的智能回答模式：

### 主要问题
1. **问题类型识别不够精准**：缺乏对常识问题、文档问题、多主题问题的精确分类
2. **回答模式单一**：没有针对不同类型问题采用不同的回答策略
3. **联网搜索集成不完善**：Tavily API虽然已配置，但缺乏智能触发机制
4. **源引用展示不清晰**：用户无法明确知道答案来源是文档知识还是联网信息
5. **多问题检索逻辑不完善**：并行检索和结果融合需要优化

### 当前代码分析
- **rag_service.py**: 已有基础的多主题处理和联网搜索框架
- **tools.py**: 已有TavilyTool实现，但集成度不高
- **answer-panel.tsx**: 前端已支持文档和通用模式区分，但需要增强

### 需要实现的功能

#### 1. 增强问题类型识别
- 实现更精确的问题分类器（常识问题、文档问题、混合问题）
- 识别问题的时效性需求（是否需要联网搜索）
- 识别多主题问题的复杂度

#### 2. 智能回答策略
- **常识问题模式**：直接回答 + 可选联网补充
- **文档问题模式**：强制基于文档回答 + 明确引用
- **混合问题模式**：文档基础 + 联网增强 + 结构化展示
- **多主题模式**：并行检索 + 分主题展示

#### 3. 联网搜索智能触发
- 基于问题关键词自动判断是否需要联网
- 时间敏感问题（如新闻、最新数据）自动联网
- 文档内容不足时自动联网补充

#### 4. 源引用增强
- 明确区分文档来源和联网来源
- 提供可信度评分
- 支持来源交叉验证

#### 5. 前端界面增强
- 支持多种回答模式的展示
- 清晰的来源标识
- 联网/文档切换开关

### 技术实现要点

#### 问题类型识别器 (enhanced_intent_classifier.py)
- 基于关键词和LLM的双重分类
- 时效性检测
- 复杂度评估

#### 增强RAG服务 (rag_service.py)
- 新增回答策略选择器
- 改进多主题处理逻辑
- 优化联网搜索集成

#### 联网搜索服务增强 (web_search_service.py)  
- 智能触发逻辑
- 结果质量评估
- 与文档结果的融合

#### 前端组件更新 (answer-panel.tsx)
- 多模式答案展示
- 来源类型标识
- 交互式引用查看

### 关键文件路径
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/rag_service.py` (主要修改)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/enhanced_intent_classifier.py` (新建)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/web_search_service.py` (增强)
- `/home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/answer/answer-panel.tsx` (更新)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/config.py` (配置增强)

### 环境变量需求
- TAVILY_API_KEY (已配置)
- 问题分类阈值参数
- 联网搜索触发参数

### 期望效果
1. 用户提问时系统自动识别问题类型和最佳回答策略
2. 常识问题直接回答，文档问题强制引用，混合问题智能结合
3. 时效性问题自动联网获取最新信息
4. 多主题问题分条列示，每个主题都有明确来源
5. 前端界面清晰展示答案来源类型和可信度

---
REQUIREMENTS AFTER FIX:

1. Create a detailed fix report in docs/ directory: docs/codex-fix-2025-11-08T03-23-37-913Z.md

2. The report MUST use the following Markdown format:

# Bug Fix Report

## Problem Description
RAG系统混合检索增强与问题类型识别功能实现

## 问题背景
当前RAG系统需要增强混合检索功能，实现针对不同问题类型的智能回答模式：

### 主要问题
1. **问题类型识别不够精准**：缺乏对常识问题、文档问题、多主题问题的精确分类
2. **回答模式单一**：没有针对不同类型问题采用不同的回答策略
3. **联网搜索集成不完善**：Tavily API虽然已配置，但缺乏智能触发机制
4. **源引用展示不清晰**：用户无法明确知道答案来源是文档知识还是联网信息
5. **多问题检索逻辑不完善**：并行检索和结果融合需要优化

### 当前代码分析
- **rag_service.py**: 已有基础的多主题处理和联网搜索框架
- **tools.py**: 已有TavilyTool实现，但集成度不高
- **answer-panel.tsx**: 前端已支持文档和通用模式区分，但需要增强

### 需要实现的功能

#### 1. 增强问题类型识别
- 实现更精确的问题分类器（常识问题、文档问题、混合问题）
- 识别问题的时效性需求（是否需要联网搜索）
- 识别多主题问题的复杂度

#### 2. 智能回答策略
- **常识问题模式**：直接回答 + 可选联网补充
- **文档问题模式**：强制基于文档回答 + 明确引用
- **混合问题模式**：文档基础 + 联网增强 + 结构化展示
- **多主题模式**：并行检索 + 分主题展示

#### 3. 联网搜索智能触发
- 基于问题关键词自动判断是否需要联网
- 时间敏感问题（如新闻、最新数据）自动联网
- 文档内容不足时自动联网补充

#### 4. 源引用增强
- 明确区分文档来源和联网来源
- 提供可信度评分
- 支持来源交叉验证

#### 5. 前端界面增强
- 支持多种回答模式的展示
- 清晰的来源标识
- 联网/文档切换开关

### 技术实现要点

#### 问题类型识别器 (enhanced_intent_classifier.py)
- 基于关键词和LLM的双重分类
- 时效性检测
- 复杂度评估

#### 增强RAG服务 (rag_service.py)
- 新增回答策略选择器
- 改进多主题处理逻辑
- 优化联网搜索集成

#### 联网搜索服务增强 (web_search_service.py)  
- 智能触发逻辑
- 结果质量评估
- 与文档结果的融合

#### 前端组件更新 (answer-panel.tsx)
- 多模式答案展示
- 来源类型标识
- 交互式引用查看

### 关键文件路径
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/rag_service.py` (主要修改)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/enhanced_intent_classifier.py` (新建)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/services/web_search_service.py` (增强)
- `/home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/answer/answer-panel.tsx` (更新)
- `/home/reggie/vscode_folder/RAG/rag-system/backend/config.py` (配置增强)

### 环境变量需求
- TAVILY_API_KEY (已配置)
- 问题分类阈值参数
- 联网搜索触发参数

### 期望效果
1. 用户提问时系统自动识别问题类型和最佳回答策略
2. 常识问题直接回答，文档问题强制引用，混合问题智能结合
3. 时效性问题自动联网获取最新信息
4. 多主题问题分条列示，每个主题都有明确来源
5. 前端界面清晰展示答案来源类型和可信度

## Fix Time
2025-11-08T03:23:37.913Z

## Modified Files
List all modified files with their full paths

## Detailed Changes
For each file, provide detailed explanation:

### File: filename
**Changes**: Brief description

**Before**:
```language
original code
```

**After**:
```language
new code
```

**Reason**: Why this change was made

## Testing Recommendations
1. Unit test commands
2. Manual testing steps
3. Expected results

## Notes
Important notes about these changes

## Summary
Summarize this fix in 1-2 sentences

---
Report generated: 2025-11-08T03:23:37.913Z
Fix tool: OpenAI Codex
