<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')
const expanded = ref(null)
const detail = ref(null)

onMounted(async () => {
  try {
    rows.value = await getJson('/api/handovers')
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function toggleDetail(h) {
  if (expanded.value === h.id) {
    expanded.value = null
    detail.value = null
    return
  }
  expanded.value = h.id
  detail.value = null
  try {
    detail.value = await getJson(`/api/handovers/${h.id}`)
  } catch (e) {
    err.value = String(e.message || e)
  }
}
</script>

<template>
  <div>
    <h1>交班记录</h1>
    <p class="lead">每单交班留档：双方班次、清单批次数、拒收键数、最终状态；拒收记录独立落库，点开可查原因。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>单号</th><th>交班方</th><th>接班方</th><th>批次数</th><th>拒收数</th><th>状态</th><th>开始</th><th>结束</th><th>拒收明细</th></tr>
        </thead>
        <tbody>
          <template v-for="h in rows" :key="h.id">
            <tr>
              <td>#{{ h.id }}</td>
              <td>{{ h.from_shift_name }}</td>
              <td>{{ h.to_shift_name }}</td>
              <td>{{ h.batch_count }}</td>
              <td>{{ h.rejected_count }}</td>
              <td>
                <span class="tag" :class="{ on: h.status === '已完成', bad: h.status === '失败' }">{{ h.status }}</span>
              </td>
              <td>{{ h.started_at }}</td>
              <td>{{ h.finished_at || '—' }}</td>
              <td>
                <button class="link" @click="toggleDetail(h)">
                  {{ expanded === h.id ? '收起' : '查看' }}
                </button>
              </td>
            </tr>
            <tr v-if="expanded === h.id">
              <td colspan="9">
                <p v-if="!detail" class="muted">加载中…</p>
                <template v-else>
                  <p class="lead" style="margin:0 0 8px">
                    分桶：清单 {{ detail.buckets.清单数 }} · 过户 {{ detail.buckets.过户数 }} · 拒收 {{ detail.buckets.拒收数 }}
                    <template v-if="detail.reason"> · 失败原因：{{ detail.reason }}</template>
                  </p>
                  <div v-if="detail.proof" class="proof">
                    <p class="lead" style="margin:0 0 8px">
                      分桶证明
                      <span class="tag" :class="{ on: detail.proof['一致'], bad: !detail.proof['一致'] }">
                        {{ detail.proof['一致'] ? '一致' : '不一致' }}
                      </span>
                      · 纳入 {{ detail.proof.included_count }} · 拒收 {{ detail.proof.rejected_count }} ·
                      过户 {{ detail.proof.transferred_count }} · 交班方在途 {{ detail.proof.from_inflight_count }} ·
                      接班方在途 {{ detail.proof.to_inflight_count }}
                    </p>
                    <p class="lead" style="margin:0 0 8px">
                      纳入键：{{ (detail.proof.proof?.纳入键 || []).join('、') || '—' }}
                    </p>
                    <p class="lead" style="margin:0 0 8px">
                      过户键：{{ (detail.proof.proof?.过户键 || []).join('、') || '—' }}
                    </p>
                    <p class="lead" style="margin:0 0 8px">
                      拒收键：{{ (detail.proof.proof?.拒收键 || []).join('、') || '—' }}
                    </p>
                  </div>
                  <p v-else class="muted">本单尚未完成，暂无分桶证明。</p>
                  <table v-if="detail.rejections.length">
                    <thead><tr><th>业务键</th><th>标题</th><th>拒收原因</th><th>标记时间</th></tr></thead>
                    <tbody>
                      <tr v-for="r in detail.rejections" :key="r.batch_id">
                        <td>{{ r.biz_key }}</td>
                        <td>{{ r.title }}</td>
                        <td>{{ r.reason }}</td>
                        <td>{{ r.created_at }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p v-else class="muted">本单无拒收记录。</p>
                </template>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
