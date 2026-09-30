<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { autoLoginLangfuse } from './services/langfuse'
const route = useRoute()
watch(() => route.fullPath, () => { void autoLoginLangfuse() }, { immediate: true })
</script>

<template><router-view /></template>
