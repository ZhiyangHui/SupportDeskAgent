<script setup lang="ts">
// 员工登录必须提供企业编号，与客户账号系统独立。
import AccountAccess from "@/components/AccountAccess.vue";
</script>
<template><AccountAccess audience="staff" /></template>
