<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  visible: boolean
}>()

const router = useRouter()
const isTransitioning = ref(false)
const isHovered = ref(false)

watch(() => props.visible, (newVal) => {
  if (newVal) {
    // Returning to home: reset state
    isTransitioning.value = false
  } else {
    // Navigating away: keep isTransitioning=true to maintain the expanded dark background
    // while the parent opacity fades out.
  }
})

const handleClick = async () => {
  if (!props.visible) return
  isTransitioning.value = true
  
  // Wait for sphere to expand before navigating
  setTimeout(() => {
    router.push('/ai-chat')
  }, 350)
}
</script>

<template>
  <div class="fixed z-[9999] bottom-5 right-4 sm:bottom-8 sm:right-8 flex items-center justify-center pointer-events-none ai-orb-wrap">
    
    <!-- 1. Transition Overlay -->
    <!-- Removed duration-1000 from parent and handling fade here for better control -->
    <div 
      class="absolute rounded-full transition-all ease-in-out pointer-events-none"
      :class="[
        isTransitioning ? 'scale-[60] opacity-100 duration-500' : 'scale-0 opacity-0 duration-300',
        !visible && isTransitioning ? '!opacity-0 !duration-700' : '' 
      ]"
      style="width: 4rem; height: 4rem; background: #131314;"
    ></div>

    <!-- 2. The Orb Container -->
    <!-- When visible=false, we fade out quickly -->
    <div 
      class="relative flex items-center justify-center transition-all ease-in-out"
      :class="[
        visible ? 'opacity-100 pointer-events-auto duration-300' : 'opacity-0 pointer-events-none duration-300 translate-y-4',
        isTransitioning ? '!opacity-0 !duration-200 !scale-0' : 'scale-100'
      ]"
    >
        <!-- Outer Glow (Ambient Energy) - Hidden during transition -->
        <div 
            v-if="!isTransitioning"
            class="absolute w-full h-full rounded-full blur-xl transition-all duration-1000"
            :class="[
                isHovered ? 'bg-blue-500/60 scale-150' : 'bg-purple-600/40 scale-125',
                'animate-pulse-slow'
            ]"
        ></div>

        <!-- Main Orb Body -->
        <div 
            @click="handleClick"
            @mouseenter="isHovered = true"
            @mouseleave="isHovered = false"
            class="relative w-12 h-12 sm:w-14 sm:h-14 rounded-full cursor-pointer transition-transform duration-300 hover:scale-105 active:scale-95 glass-orb overflow-hidden"
            role="button"
            aria-label="Open AI Chat"
        >
            <!-- Deep Space Background -->
            <div class="absolute inset-0 bg-[#000000]"></div>

            <!-- Fluid/Smoke Effect (Keep complex filters ONLY on the small orb) -->
            <div class="absolute inset-[-50%] w-[200%] h-[200%] opacity-90 mix-blend-screen filter blur-[12px]">
                <!-- Blob 1: Cyan/Blue -->
                <div class="absolute top-[25%] left-[25%] w-[50%] h-[50%] rounded-[40%] bg-gradient-to-tr from-cyan-400 to-blue-600 animate-blob mix-blend-screen opacity-90"></div>
                <!-- Blob 2: Purple/Pink -->
                <div class="absolute top-[25%] right-[25%] w-[50%] h-[50%] rounded-[45%] bg-gradient-to-bl from-purple-500 to-pink-600 animate-blob animation-delay-2000 mix-blend-screen opacity-90"></div>
                <!-- Blob 3: Deep Blue/Indigo -->
                <div class="absolute bottom-[20%] left-[30%] w-[60%] h-[60%] rounded-[35%] bg-gradient-to-t from-indigo-500 to-violet-600 animate-blob animation-delay-4000 mix-blend-screen opacity-90"></div>
            </div>

            <!-- Matte Surface Layer -->
            <div class="absolute inset-0 rounded-full bg-white/5 backdrop-blur-[1px] pointer-events-none"></div>

            <!-- Highlights -->
            <div class="absolute inset-0 rounded-full bg-gradient-to-b from-white/20 to-transparent opacity-80 pointer-events-none"></div>
            <div class="absolute inset-0 rounded-full bg-gradient-to-t from-blue-400/20 via-transparent to-transparent opacity-70 pointer-events-none"></div>
            <div class="absolute top-3 left-3 w-4 h-2 rounded-[100%] bg-white/40 blur-[2px] transform -rotate-45 pointer-events-none"></div>
            <div class="absolute inset-0 rounded-full border border-white/20 shadow-[inset_0_0_10px_rgba(255,255,255,0.1)] pointer-events-none"></div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.glass-orb {
  box-shadow: 
    0 10px 30px -5px rgba(0, 0, 0, 0.6),
    inset 0 0 20px rgba(255, 255, 255, 0.05);
  transform: translateZ(0); /* Hardware acceleration */
}

.animate-pulse-slow {
    animation: pulse-glow 4s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 0.4; transform: scale(1.25); }
  50% { opacity: 0.6; transform: scale(1.35); }
}

.animate-blob {
  animation: blob 10s infinite cubic-bezier(0.4, 0, 0.2, 1);
}

.animation-delay-2000 {
  animation-delay: 2s;
}

.animation-delay-4000 {
  animation-delay: 4s;
}

@keyframes blob {
  0% { transform: translate(0px, 0px) scale(1) rotate(0deg); }
  33% { transform: translate(5px, -8px) scale(1.05) rotate(120deg); }
  66% { transform: translate(-3px, 5px) scale(0.95) rotate(240deg); }
  100% { transform: translate(0px, 0px) scale(1) rotate(360deg); }
}

@media (max-width: 768px) {
  .ai-orb-wrap {
    bottom: max(0.75rem, env(safe-area-inset-bottom));
  }
}
</style>
