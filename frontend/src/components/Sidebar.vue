<template>
  <aside class="sidebar">
    <div class="logo">
      <el-icon :size="22" color="#409eff"><Reading /></el-icon>
      <span class="logo-text">文献精读助手</span>
    </div>
    <el-menu
      :default-active="activeMenu"
      router
      class="nav-menu"
      background-color="#304156"
      text-color="#bfcbd9"
      active-text-color="#409eff"
    >
      <el-menu-item index="/upload">
        <el-icon><UploadFilled /></el-icon>
        <span>文献上传</span>
      </el-menu-item>
      <el-menu-item index="/qa">
        <el-icon><ChatDotRound /></el-icon>
        <span>深度问答</span>
      </el-menu-item>
      <el-menu-item index="/graph">
        <el-icon><Share /></el-icon>
        <span>知识图谱</span>
      </el-menu-item>
      <el-menu-item index="/review">
        <el-icon><Document /></el-icon>
        <span>综述生成</span>
      </el-menu-item>
    </el-menu>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
// 当前路由高亮菜单项
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 220px;
  background: #304156;
  z-index: 100;
  overflow-y: auto;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 16px;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  border-bottom: 1px solid #1f2d3d;
}
.nav-menu {
  border-right: none;
}
.nav-menu .el-menu-item {
  display: flex;
  align-items: center;
}
</style>
