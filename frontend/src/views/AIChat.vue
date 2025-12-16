<script setup lang="ts">
import { computed, onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import {
  Menu,
  Plus,
  MessageSquare,
  HelpCircle,
  Send,
  Mic,
  Image as ImageIcon,
  MoreVertical,
  List,
  Box,
  LogOut,
  ExternalLink,
  X
} from 'lucide-vue-next'
import { deviceLinkApi } from '@/api/deviceLink'
import type { DeviceInfo } from '@/types'
import { renderMarkdown } from '@/utils/markdownRenderer'

const sidebarOpen = ref(true)
const inputMessage = ref('')
const showUserMenu = ref(false)
const chatContainerRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const inputAreaRef = ref<HTMLElement | null>(null)
const mentionDropdownRef = ref<HTMLElement | null>(null)
const userMenuRef = ref<HTMLElement | null>(null)
const userButtonRef = ref<HTMLElement | null>(null)
const devices = ref<DeviceInfo[]>([])
const isLoadingDevices = ref(false)
const mentionVisible = ref(false)
const mentionKeyword = ref('')
const mentionSelectedIndex = ref(0)
const mentionStart = ref<number | null>(null)
const targetDeviceId = ref<string | null>(null)
const targetDeviceName = ref<string | null>(null)

// Handle click outside to close menu
const handleClickOutside = (event: MouseEvent) => {
  if (showUserMenu.value &&
      userMenuRef.value &&
      userButtonRef.value &&
      !userMenuRef.value.contains(event.target as Node) && 
      !userButtonRef.value.contains(event.target as Node)) {
    showUserMenu.value = false
  }

  if (
    mentionVisible.value &&
    mentionDropdownRef.value &&
    inputAreaRef.value &&
    !mentionDropdownRef.value.contains(event.target as Node) &&
    !inputAreaRef.value.contains(event.target as Node)
  ) {
    mentionVisible.value = false
    mentionKeyword.value = ''
    mentionStart.value = null
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  fetchDevices()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

const chatHistory = ref([
  {
    role: 'ai',
    content: '你好！我是 Raven AI。有什么我可以帮你的吗？'
  }
])
const sessionId = ref<string | null>(null)
const isSending = ref(false)

const toggleSidebar = () => {
  sidebarOpen.value = !sidebarOpen.value
}

const toggleUserMenu = () => {
  showUserMenu.value = !showUserMenu.value
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainerRef.value) {
    chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight
  }
}

// Watch for chat history changes to scroll to bottom
watch(chatHistory, () => {
  scrollToBottom()
}, { deep: true })

// Construct 8085 URLs dynamically based on current hostname
const getServiceUrl = (path: string) => {
  const hostname = window.location.hostname
  return `http://${hostname}:8085${path}`
}

const fetchDevices = async () => {
  isLoadingDevices.value = true
  try {
    const res = await deviceLinkApi.listDevices()
    devices.value = res.devices || []
  } catch (error) {
    console.error('加载设备列表失败', error)
  } finally {
    isLoadingDevices.value = false
  }
}

const filteredDevices = computed(() => {
  const keyword = mentionKeyword.value.trim().toLowerCase()
  const list = devices.value.slice().sort((a, b) => {
    if (a.status === b.status) return 0
    return a.status === 'online' ? -1 : 1
  })
  if (!keyword) return list
  return list.filter(device => {
    const name = device.name || ''
    return (
      name.toLowerCase().includes(keyword) ||
      device.id.toLowerCase().includes(keyword)
    )
  })
})

watch(filteredDevices, (list) => {
  if (mentionSelectedIndex.value >= list.length) {
    mentionSelectedIndex.value = 0
  }
})

const deviceStatusDotClass = (status: DeviceInfo['status']) =>
  status === 'online' ? 'bg-green-500' : 'bg-gray-300'

const resetMentionState = () => {
  mentionVisible.value = false
  mentionKeyword.value = ''
  mentionSelectedIndex.value = 0
  mentionStart.value = null
}

const renderAiMessage = (content: string) =>
  renderMarkdown(content || '', {
    wrapperClass: 'markdown-content text-gray-900'
  })

const updateMentionState = (event?: Event) => {
  const value = inputMessage.value
  const target = (event?.target as HTMLTextAreaElement | null) || textareaRef.value
  const cursor = target?.selectionStart ?? value.length
  const lastAt = value.lastIndexOf('@', cursor - 1)
  if (lastAt === -1) {
    resetMentionState()
    return
  }
  const afterAt = value.slice(lastAt + 1, cursor)
  if (afterAt.includes(' ') || afterAt.includes('\n') || afterAt.includes('\t')) {
    resetMentionState()
    return
  }
  mentionVisible.value = true
  mentionKeyword.value = afterAt
  mentionSelectedIndex.value = 0
  mentionStart.value = lastAt
}

const applyDeviceSelection = (device: DeviceInfo) => {
  targetDeviceId.value = device.id
  targetDeviceName.value = device.name || device.id

  // Replace the mention keyword with the selected device name for clarity
  const value = inputMessage.value
  const cursor = textareaRef.value?.selectionStart ?? value.length
  if (mentionStart.value !== null) {
    const before = value.slice(0, mentionStart.value)
    const after = value.slice(cursor)
    const insertion = `@${targetDeviceName.value} `
    inputMessage.value = `${before}${insertion}${after}`
    nextTick(() => {
      const pos = before.length + insertion.length
      textareaRef.value?.setSelectionRange(pos, pos)
    })
  } else {
    const insertion = `@${targetDeviceName.value} `
    inputMessage.value = value ? `${value} ${insertion}` : insertion
  }

  resetMentionState()
}

const clearTargetDevice = () => {
  targetDeviceId.value = null
  targetDeviceName.value = null
}

const applyStreamEvent = (payload: any, messageIndex: number) => {
  const type = payload?.event || payload?.type
  if (payload?.session_id) {
    sessionId.value = payload.session_id
  }

  const targetMessage = chatHistory.value[messageIndex]
  if (!targetMessage) return

  if (type === 'chunk' && typeof payload?.content === 'string') {
    const chunk = payload.content
    // 如果还在"正在思考..."状态，等待有实际内容才清除
    if (targetMessage.content === '正在思考...') {
      // 跳过开头的空白字符
      const trimmedChunk = chunk.trimStart()
      if (trimmedChunk) {
        targetMessage.content = trimmedChunk
      }
      // 如果是纯空白，保持"正在思考..."状态
    } else {
      targetMessage.content += chunk
    }
  } else if (type === 'done') {
    if (typeof payload?.answer === 'string' && payload.answer) {
      // 去除开头的空白字符
      targetMessage.content = payload.answer.trimStart()
    } else if (!targetMessage.content || targetMessage.content === '正在思考...') {
      targetMessage.content = '（无回复内容）'
    }
  } else if (type === 'error') {
    targetMessage.content = `调用后端失败：${payload?.message || '未知错误'}`
  }
}

const processSseBuffer = (buffer: string, messageIndex: number) => {
  let remaining = buffer.replace(/\r\n/g, '\n')
  while (true) {
    const idx = remaining.indexOf('\n\n')
    if (idx === -1) break
    const raw = remaining.slice(0, idx)
    remaining = remaining.slice(idx + 2)
    const trimmed = raw.trim()
    if (!trimmed.startsWith('data:')) continue
    const jsonStr = trimmed.replace(/^data:\s*/, '')
    if (!jsonStr) continue
    try {
      const payload = JSON.parse(jsonStr)
      applyStreamEvent(payload, messageIndex)
    } catch (err) {
      console.error('解析流式数据失败', err, jsonStr)
    }
  }
  return remaining
}

const handleKeydown = (event: KeyboardEvent) => {
  if (mentionVisible.value && filteredDevices.value.length > 0) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionSelectedIndex.value =
        (mentionSelectedIndex.value + 1) % filteredDevices.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionSelectedIndex.value =
        (mentionSelectedIndex.value - 1 + filteredDevices.value.length) % filteredDevices.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      const device = filteredDevices.value[mentionSelectedIndex.value]
      if (device) applyDeviceSelection(device)
      return
    }
  }

  if (event.key === 'Escape' && mentionVisible.value) {
    resetMentionState()
    return
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

const handleInput = (event: Event) => {
  updateMentionState(event)
}

const sendMessage = async () => {
  if (isSending.value) return
  const content = inputMessage.value.trim()
  if (!content) return

  // 记录用户消息
  const userMessage = {
    role: 'user',
    content
  }
  chatHistory.value.push(userMessage)

  // 构造历史（不含当前用户消息，因为会通过message字段单独发送）
  // 只发送之前的对话历史
  const historyPayload = chatHistory.value.slice(0, -1).map(msg => ({
    role: msg.role,
    content: msg.content
  }))

  // 占位回复
  chatHistory.value.push({
    role: 'ai',
    content: '正在思考...'
  })
  // 记录 AI 消息在数组中的索引，用于后续更新
  const aiMessageIndex = chatHistory.value.length - 1

  inputMessage.value = ''
  resetMentionState()
  isSending.value = true

  try {
    const payload = {
      message: content,
      session_id: sessionId.value || undefined,
      history: historyPayload,
      remember: true,
      target_device_id: targetDeviceId.value || undefined,
      target_device_name: targetDeviceName.value || undefined
    }

    const resp = await fetch(getServiceUrl('/api/v1/ai-chat/chat/stream'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    if (!resp.body) {
      throw new Error('响应体为空，无法流式读取')
    }

    console.log('[SSE] resp.body 存在，开始流式读取')
    console.log('[SSE] TextDecoderStream 支持:', typeof TextDecoderStream !== 'undefined')

    const textStream = resp.body && typeof TextDecoderStream !== 'undefined'
      ? resp.body.pipeThrough(new TextDecoderStream())
      : null

    const reader = textStream
      ? textStream.getReader()
      : null
    const binaryReader = !textStream && resp.body ? resp.body.getReader() : null
    const decoder = !textStream ? new TextDecoder('utf-8') : null
    let buffer = ''

    console.log('[SSE] reader:', !!reader, 'binaryReader:', !!binaryReader)

    if (reader) {
      console.log('[SSE] 使用 TextDecoderStream reader')
      while (true) {
        const { value, done } = await reader.read()
        console.log('[SSE] read result - done:', done, 'value length:', value?.length)
        if (value) {
          console.log('[SSE] 收到数据:', value.substring(0, 200))
          buffer += value
          buffer = processSseBuffer(buffer, aiMessageIndex)
        }
        if (done) break
      }
    } else if (binaryReader && decoder) {
      console.log('[SSE] 使用 binary reader')
      while (true) {
        const { value, done } = await binaryReader.read()
        console.log('[SSE] read result - done:', done, 'value:', value?.length)
        if (value) {
          const decoded = decoder.decode(value, { stream: !done })
          console.log('[SSE] 解码后数据:', decoded.substring(0, 200))
          buffer += decoded
          buffer = processSseBuffer(buffer, aiMessageIndex)
        }
        if (done) break
      }
    } else {
      console.error('[SSE] 没有可用的 reader!')
    }

    console.log('[SSE] 循环结束，剩余 buffer:', buffer)

    if (buffer.trim()) {
      processSseBuffer(buffer + '\n\n', aiMessageIndex)
    }

    if (chatHistory.value[aiMessageIndex].content === '正在思考...') {
      chatHistory.value[aiMessageIndex].content = '（无回复内容）'
    }
  } catch (error: any) {
    console.error('===== 请求失败 =====')
    console.error('错误信息:', error)
    chatHistory.value[aiMessageIndex].content = `调用后端失败：${error?.message || String(error)}`
  } finally {
    isSending.value = false
    console.log('===== 请求结束 =====')
  }
}
</script>

<template>
  <div class="flex h-full bg-white text-gray-900 font-sans overflow-hidden">
    <!-- Sidebar -->
    <div 
      :class="[
        'flex flex-col bg-[#F0F4F9] transition-all duration-300 ease-in-out',
        sidebarOpen ? 'w-64' : 'w-16'
      ]"
    >
      <div class="p-4 flex items-center justify-between">
        <button @click="toggleSidebar" class="p-2 hover:bg-gray-200 rounded-full text-gray-500 hover:text-gray-900 transition-colors">
          <Menu class="w-5 h-5" />
        </button>
      </div>

      <div class="px-3 py-2">
        <button 
          class="flex items-center gap-3 w-full p-3 rounded-full bg-[#DDE3EA] hover:bg-gray-200 text-gray-700 hover:text-gray-900 transition-colors border border-transparent hover:border-gray-300"
          :class="{ 'justify-center': !sidebarOpen }"
        >
          <Plus class="w-4 h-4 text-gray-500" />
          <span v-if="sidebarOpen" class="text-sm font-medium">新对话</span>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto mt-4 px-3">
        <div v-if="sidebarOpen" class="mb-2 px-3 text-xs font-medium text-gray-500">最近对话</div>
        
        <!-- Recent Chats Mockup -->
        <div class="space-y-1">
          <button 
            v-for="i in 3" 
            :key="i"
            class="flex items-center gap-3 w-full p-2 rounded-full hover:bg-gray-200 text-gray-700 hover:text-gray-900 transition-colors group text-left"
            :class="{ 'justify-center': !sidebarOpen }"
          >
            <MessageSquare class="w-4 h-4 text-gray-500" />
            <span v-if="sidebarOpen" class="text-sm truncate">历史对话主题 {{ i }}</span>
            <button v-if="sidebarOpen" class="ml-auto opacity-0 group-hover:opacity-100 p-1 hover:text-gray-900 text-gray-500">
              <MoreVertical class="w-3 h-3" />
            </button>
          </button>
        </div>
      </div>

      <div class="p-3 mt-auto relative">
        <!-- User Menu Dropdown -->
        <div ref="userMenuRef" v-if="showUserMenu && sidebarOpen" class="absolute bottom-full left-3 w-56 mb-2 bg-[#F0F4F9] rounded-xl shadow-xl overflow-hidden border border-gray-200 z-50">
          <div class="py-1">
            <button class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors w-full text-left">
              <HelpCircle class="w-4 h-4 text-gray-500" />
              <span>帮助</span>
            </button>
            <div class="h-px bg-gray-200 my-1"></div>
            <a :href="getServiceUrl('/')" class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors">
              <List class="w-4 h-4 text-gray-500" />
              <span>日志列表</span>
            </a>
            <a :href="getServiceUrl('/raven-manager')" class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors">
              <Box class="w-4 h-4 text-gray-500" />
              <span>Raven 包管理</span>
            </a>
            <div class="h-px bg-gray-200 my-1"></div>
             <div class="flex items-center gap-3 px-4 py-3 text-sm text-gray-500 hover:bg-gray-200 transition-colors cursor-pointer">
              <LogOut class="w-4 h-4" />
              <span>退出登录</span>
            </div>
          </div>
        </div>

        <!-- User Profile / Activity -->
        <div 
          ref="userButtonRef"
          @click="toggleUserMenu"
          class="mt-2 flex items-center gap-3 p-2 rounded-full hover:bg-gray-200 cursor-pointer relative" 
          :class="{ 'justify-center': !sidebarOpen, 'bg-gray-200': showUserMenu }"
        >
           <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white">
             U
           </div>
           <div v-if="sidebarOpen" class="text-xs text-gray-700">
             <div>用户</div>
             <div class="text-[10px] text-gray-500">user@example.com</div>
           </div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col h-full relative">
      <!-- Top Bar -->
      <div class="h-16 flex items-center justify-between px-6">
        <div class="flex items-center gap-3 flex-wrap">
          <div class="flex items-center gap-2">
            <span class="text-xl font-medium bg-gradient-to-r from-blue-400 via-purple-400 to-red-400 bg-clip-text text-transparent">Raven AI</span>
          </div>
          <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#F0F4F9] text-xs text-gray-700">
            <span class="font-medium text-gray-800">目标设备</span>
            <span
              v-if="targetDeviceName"
              class="px-2 py-0.5 rounded-full bg-white border border-gray-200 text-gray-900 font-semibold"
            >
              {{ targetDeviceName }}
            </span>
            <span v-else class="text-gray-500">未选择</span>
            <button
              v-if="targetDeviceName"
              class="p-1 rounded-full hover:bg-gray-200 text-gray-500"
              @click="clearTargetDevice"
              title="清除已选设备"
              type="button"
            >
              <X class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <div class="flex items-center gap-4">
            <a 
              :href="getServiceUrl('/')" 
              class="flex items-center gap-2 px-4 py-2 rounded-full bg-black text-white text-sm font-medium hover:bg-gray-800 transition-colors shadow-sm"
            >
                <span>返回平台</span>
                <ExternalLink class="w-3.5 h-3.5" />
            </a>
        </div>
      </div>

      <!-- Chat Area -->
      <div ref="chatContainerRef" class="flex-1 overflow-y-auto px-4 md:px-20 py-6 scrollbar-hide scroll-smooth">
        <div class="max-w-3xl mx-auto space-y-8">
          
          <template v-if="chatHistory.length === 0">
            <div class="mt-20">
              <h1 class="text-5xl font-medium bg-gradient-to-r from-blue-500 via-purple-500 to-red-500 bg-clip-text text-transparent w-fit mb-2">你好，用户</h1>
              <h2 class="text-5xl font-medium text-[#444746] mb-12">今天有什么我可以帮你的吗？</h2>
              
              <!-- Suggestions -->
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div v-for="item in ['制定旅行计划', '代码审查', '撰写邮件', '头脑风暴']" :key="item" 
                  class="bg-[#F0F4F9] p-4 rounded-xl hover:bg-gray-200 cursor-pointer transition-colors h-40 flex flex-col justify-between"
                >
                  <span class="text-gray-700 text-sm">{{ item }}</span>
                  <div class="w-8 h-8 rounded-full bg-white flex items-center justify-center self-end shadow-sm">
                     <MessageSquare class="w-4 h-4 text-gray-500" />
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-else>
             <div 
               v-for="(msg, idx) in chatHistory" 
               :key="idx" 
               class="flex gap-4 group w-full"
               :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
             >
               <!-- AI Avatar (Left side only) -->
               <div 
                 v-if="msg.role === 'ai'"
                 class="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center mt-1"
               >
                 <div class="w-6 h-6 rounded-full bg-gradient-to-tr from-blue-500 via-purple-500 to-red-500 animate-pulse-slow"></div>
               </div>

               <!-- Message Content Bubble -->
               <div 
                 class="max-w-[80%] rounded-2xl px-5 py-3 text-base leading-relaxed"
                 :class="[
                   msg.role === 'user' 
                     ? 'bg-[#F0F4F9] text-gray-900 rounded-tr-sm whitespace-pre-wrap' 
                     : 'bg-transparent text-gray-900 px-0'
                 ]"
               >
                 <template v-if="msg.content === '正在思考...'">
                   <span class="thinking-text">正在思考...</span>
                 </template>
                 <template v-else-if="msg.role === 'ai'">
                   <div v-html="renderAiMessage(msg.content)"></div>
                 </template>
                 <template v-else>
                   {{ msg.content }}
                 </template>
               </div>
             </div>
          </template>

        </div>
      </div>

      <!-- Input Area -->
      <div class="p-4 md:pb-6">
        <div
          ref="inputAreaRef"
          class="max-w-3xl mx-auto bg-[#F0F4F9] rounded-3xl p-2 md:p-3 relative group focus-within:bg-gray-100 transition-colors"
        >
          <div
            v-if="mentionVisible"
            ref="mentionDropdownRef"
            class="absolute left-0 right-0 bottom-full mb-3 bg-white border border-gray-200 rounded-2xl shadow-xl overflow-hidden max-h-64 z-30"
          >
            <div class="px-4 py-3 text-sm text-gray-600 border-b border-gray-100 flex items-center justify-between">
              <span>选择要发送指令的设备</span>
              <span class="text-xs text-gray-400">输入 @ 或设备名进行过滤</span>
            </div>
            <div v-if="isLoadingDevices" class="px-4 py-3 text-sm text-gray-500">设备列表加载中...</div>
            <div v-else-if="!filteredDevices.length" class="px-4 py-3 text-sm text-gray-500">暂无匹配的设备</div>
            <template v-else>
              <button
                v-for="(device, idx) in filteredDevices"
                :key="device.id"
                type="button"
                class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                :class="{ 'bg-gray-100': idx === mentionSelectedIndex }"
                @mousedown.prevent="applyDeviceSelection(device)"
                @mouseenter="mentionSelectedIndex = idx"
              >
                <span
                  class="w-2 h-2 rounded-full"
                  :class="deviceStatusDotClass(device.status)"
                ></span>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-gray-900 truncate">{{ device.name || device.id }}</span>
                    <span class="text-[11px] text-gray-500 uppercase">{{ device.status === 'online' ? '在线' : '离线' }}</span>
                  </div>
                  <div class="text-xs text-gray-500 truncate">ID: {{ device.id }}</div>
                </div>
                <div v-if="device.models?.length" class="text-[11px] text-gray-500 truncate max-w-[120px] text-right">
                  {{ device.models.slice(0, 2).join(', ') }}<span v-if="device.models.length > 2"> ...</span>
                </div>
              </button>
            </template>
          </div>
          <div
            v-if="targetDeviceName"
            class="flex items-center gap-2 mb-2 px-3 py-2 rounded-2xl bg-white border border-gray-200 text-sm text-gray-700"
          >
            <span class="text-gray-500">当前目标</span>
            <span class="font-semibold text-gray-900">{{ targetDeviceName }}</span>
            <button
              class="ml-auto p-1 rounded-full hover:bg-gray-100 text-gray-500"
              type="button"
              @click="clearTargetDevice"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
          <div class="flex items-end gap-2">
            <button class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors">
              <ImageIcon class="w-5 h-5" />
            </button>
            
            <textarea 
              v-model="inputMessage"
              ref="textareaRef"
              @keydown="handleKeydown"
              @input="handleInput"
              placeholder="在这里输入指令"
              class="flex-1 bg-transparent border-0 focus:ring-0 text-gray-900 resize-none max-h-32 py-2 scrollbar-hide placeholder-gray-500"
              rows="1"
              style="min-height: 44px;"
            ></textarea>
            
            <button class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors" v-if="!inputMessage">
              <Mic class="w-5 h-5" />
            </button>
            
            <button 
              @click="sendMessage"
              class="p-2 rounded-full transition-colors"
              :class="inputMessage ? 'bg-black text-white hover:bg-gray-800' : 'text-gray-400 hover:text-gray-600'"
            >
              <Send class="w-5 h-5" />
            </button>
          </div>
        </div>
        <div class="text-center text-xs text-gray-500 mt-2">
          Raven AI 可能会犯错。请核对重要信息 · 输入 @ 选择要连接的设备。
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-hide::-webkit-scrollbar {
    display: none;
}
.scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
}
.animate-pulse-slow {
  animation: pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: .7;
  }
}
.thinking-text {
  display: inline-block;
  background: linear-gradient(90deg, #9ca3af 0%, #e5e7eb 50%, #9ca3af 100%);
  background-size: 200% 100%;
  background-repeat: no-repeat;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: thinking-shimmer 1.6s ease-in-out infinite;
  font-weight: 600;
}
@keyframes thinking-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
