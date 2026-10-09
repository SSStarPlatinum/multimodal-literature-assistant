<template>
  <div class="loading-spinner" :class="{ overlay: overlay }">
    <el-icon class="is-loading" :size="size">
      <Loading />
    </el-icon>
    <span v-if="text" class="loading-text">{{ text }}</span>
  </div>
</template>

<script setup>
defineProps({
  text: { type: String, default: '加载中...' },
  size: { type: Number, default: 24 },
  overlay: { type: Boolean, default: false } // 是否作为遮罩层覆盖内容
})
</script>

<style scoped>
.loading-spinner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  color: #409eff;
}
.loading-spinner.overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.7);
  z-index: 10;
}
.loading-text {
  font-size: 13px;
}
</style>
