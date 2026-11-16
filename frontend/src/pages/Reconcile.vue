<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')
const proofs = ref({})

onMounted(async () => {
  try {
    rows.value = await getJson('/api/reconcile')
    const pairs = await Promise.all(
      rows.value.map(async (r) => {
        try {
          return [r.handover_id, await getJson(`/api/handovers/${r.handover_id}/proof`)]
        } catch {
          return [r.handover_id, null]
        }
      }),
    )
    proofs.value = Object.fromEntries(pairs)
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>交班对账</h1>
    <p class="lead">
      分桶（清单数 / 过户数 / 拒收数）与批次归属、拒收记录同源派生；
      完成态校验固定为「过户成功键 ∪ 拒收键 = 发起清单键，且三者两两不交」。
      每单完成时另留持久化分桶证明（纳入/拒收/过户三集合及两侧在途计数）。
    </p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>报告</th><th>交班单</th><th>清单数</th>
            <th>过户数</th><th>拒收数</th>
            <th>交后交班方</th><th>交后接班方</th>
            <th>证明·交班方在途</th><th>证明·接班方在途</th>
            <th>拒收键</th><th>一致</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>#{{ r.id }}</td>
            <td>#{{ r.handover_id }}</td>
            <td>{{ r.before_count }}</td>
            <td>{{ r.transferred_count }}</td>
            <td>{{ r.rejected_count }}</td>
            <td>{{ r.after_from_count }}</td>
            <td>{{ r.after_to_count }}</td>
            <td>{{ proofs[r.handover_id]?.from_inflight_count ?? '—' }}</td>
            <td>{{ proofs[r.handover_id]?.to_inflight_count ?? '—' }}</td>
            <td>{{ (r.detail?.拒收键 || []).join('、') || '—' }}</td>
            <td>
              <span class="tag" :class="{ on: r.一致, bad: !r.一致 }">{{ r.一致 ? '一致' : '不一致' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
