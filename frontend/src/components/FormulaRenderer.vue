<template>
  <!-- LaTeX 公式渲染容器，由 KaTeX 注入 HTML -->
  <span ref="container" class="formula-renderer"></span>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import katex from 'katex'

const props = defineProps({
  latex: { type: String, required: true },
  displayMode: { type: Boolean, default: false } // true 为独立行公式，false 为行内
})

const container = ref(null)

function render() {
  if (!container.value || !props.latex) return
  try {
    katex.render(props.latex, container.value, {
      displayMode: props.displayMode,
      throwOnError: false,
      errorColor: '#cc0000'
    })
  } catch (e) {
    container.value.textContent = props.latex
  }
}

onMounted(render)
watch(() => props.latex, render)
</script>

<style scoped>
.formula-renderer {
  display: inline-block;
}
</style>
