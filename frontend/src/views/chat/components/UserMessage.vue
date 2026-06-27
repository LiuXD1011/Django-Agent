<script setup lang="ts">
defineProps<{ message: any }>()

function fileSize(bytes: number) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <article class="chat-message user-message">
    <div class="paper-kicker">提问</div>
    <div v-if="message.mentioned_items?.length" class="mention-strip">
      <span v-for="item in message.mentioned_items" :key="item.id">{{ item.name || item.id }}</span>
    </div>
    <div v-if="message.images?.length" class="image-strip">
      <img v-for="(img, index) in message.images" :key="index" :src="img.url || img.data" alt="uploaded image" />
    </div>
    <div v-if="message.attachments?.length" class="attachment-strip">
      <span v-for="(file, index) in message.attachments" :key="index">{{ file.file_name || file.name }} {{ fileSize(file.file_size || file.size) }}</span>
    </div>
    <div class="message-body">{{ message.content }}</div>
  </article>
</template>
