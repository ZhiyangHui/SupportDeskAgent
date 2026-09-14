<script setup lang="ts">
// 客户账号不携带企业归属，选择企业是在登录后的业务步骤。
import AccountAccess from "@/components/AccountAccess.vue";
</script>
<template><AccountAccess audience="customer" /></template>
