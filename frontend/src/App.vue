<template>
  <TopBar v-if="!route.meta.public" />
  <router-view v-slot="{ Component, route: currentRoute }">
    <Transition name="fade" mode="out-in">
      <component :is="Component" :key="currentRoute.path" />
    </Transition>
  </router-view>
</template>

<script setup>
import { useRoute } from 'vue-router'
import TopBar from './components/TopBar.vue'

const route = useRoute()
</script>
