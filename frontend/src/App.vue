<template>
  <TopBar v-if="!route.meta.public" />
  <router-view />
</template>

<script setup>
import { useRoute } from 'vue-router'
import TopBar from './components/TopBar.vue'

const route = useRoute()
</script>
