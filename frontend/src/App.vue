<template>
  <div class="app-layout">
    <!-- 侧边栏导航 -->
    <Sidebar />
    <!-- 主内容区 -->
    <div class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </div>
  </div>
</template>

<script setup>
import Sidebar from './components/Sidebar.vue'
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
}
.app-main {
  flex: 1;
  margin-left: 220px; /* 与侧边栏宽度一致 */
  padding: 20px;
  background: #f5f7fa;
  min-height: 100vh;
  overflow-x: auto;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
