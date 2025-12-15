<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { 
  Menu, 
  Plus, 
  MessageSquare, 
  HelpCircle, 
  Send, 
  Mic, 
  Image as ImageIcon,
  MoreVertical,
  Settings,
  List,
  Box,
  LogOut,
  ExternalLink
} from 'lucide-vue-next'

const sidebarOpen = ref(true)
const inputMessage = ref('')
const showUserMenu = ref(false)
const chatContainerRef = ref<HTMLElement | null>(null)
const userMenuRef = ref<HTMLElement | null>(null)
const userButtonRef = ref<HTMLElement | null>(null)

// Handle click outside to close menu
const handleClickOutside = (event: MouseEvent) => {
  if (showUserMenu.value && 
      userMenuRef.value && 
      userButtonRef.value && 
      !userMenuRef.value.contains(event.target as Node) && 
      !userButtonRef.value.contains(event.target as Node)) {
    showUserMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
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
  const thinkingMessage = {
    role: 'ai',
    content: '正在思考...'
  }
  chatHistory.value.push(thinkingMessage)

  inputMessage.value = ''
  isSending.value = true

  try {
    const payload = {
      message: content,
      session_id: sessionId.value || undefined,
      history: historyPayload,
      remember: true
    }

    console.log('===== 发送请求到后端 =====')
    console.log('URL:', getServiceUrl('/api/v1/ai-chat/chat'))
    console.log('Payload:', payload)

    const resp = await fetch(getServiceUrl('/api/v1/ai-chat/chat'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })

    console.log('===== 收到后端响应 =====')
    console.log('Status:', resp.status)
    console.log('OK:', resp.ok)

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    const data = await resp.json()
    console.log('===== 解析后的数据 =====')
    console.log('完整响应数据:', data)
    console.log('data.answer:', data.answer)
    console.log('data.session_id:', data.session_id)
    
    if (data.session_id) {
      sessionId.value = data.session_id
      console.log('更新 session_id:', sessionId.value)
    }
    
    console.log('===== 更新消息内容 =====')
    console.log('更新前 thinkingMessage.content:', thinkingMessage.content)
    thinkingMessage.content = data.answer || '（无回复内容）'
    console.log('更新后 thinkingMessage.content:', thinkingMessage.content)
    console.log('chatHistory 长度:', chatHistory.value.length)
  } catch (error: any) {
    console.error('===== 请求失败 =====')
    console.error('错误信息:', error)
    thinkingMessage.content = `调用后端失败：${error?.message || String(error)}`
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
        <div class="flex items-center gap-2 cursor-pointer">
          <span class="text-xl font-medium bg-gradient-to-r from-blue-400 via-purple-400 to-red-400 bg-clip-text text-transparent">Raven AI</span>
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
                 class="max-w-[80%] rounded-2xl px-5 py-3 text-base leading-relaxed whitespace-pre-wrap"
                 :class="[
                   msg.role === 'user' 
                     ? 'bg-[#F0F4F9] text-gray-900 rounded-tr-sm' 
                     : 'bg-transparent text-gray-900 px-0'
                 ]"
               >
                 {{ msg.content }}
               </div>
             </div>
          </template>

        </div>
      </div>

      <!-- Input Area -->
      <div class="p-4 md:pb-6">
        <div class="max-w-3xl mx-auto bg-[#F0F4F9] rounded-3xl p-2 md:p-3 relative group focus-within:bg-gray-100 transition-colors">
          <div class="flex items-end gap-2">
            <button class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors">
              <ImageIcon class="w-5 h-5" />
            </button>
            
            <textarea 
              v-model="inputMessage"
              @keydown.enter.prevent="sendMessage"
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
          Raven AI 可能会犯错。请核对重要信息。
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
</style>
