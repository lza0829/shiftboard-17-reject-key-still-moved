<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { getJson, postJson, putJson } from '../api'

const shifts = ref([])
const fromId = ref(1)
const toId = ref(2)
const current = ref(null)
const msg = ref('')
const ok = ref(false)
const picked = reactive({})

const active = computed(() => !!current.value && current.value.status === '进行中')
const dirty = computed(() => {
  if (!active.value) return false
  const server = new Map((current.value?.rejections || []).map((r) => [r.batch_id, r.reason]))
  const localKeys = Object.keys(picked).map(Number)
  if (localKeys.length !== server.size) return true
  return localKeys.some((k) => !server.has(k) || server.get(k) !== String(picked[k] ?? '').trim())
})

function syncPicked() {
  Object.keys(picked).forEach((k) => delete picked[k])
  for (const r of current.value?.rejections || []) picked[r.batch_id] = r.reason
}

function reasonOf(batchId) {
  const r = (current.value?.rejections || []).find((x) => x.batch_id === batchId)
  return r ? r.reason : ''
}

async function refresh() {
  shifts.value = await getJson('/api/shifts')
  const logs = await getJson('/api/handovers')
  const cur = logs.find((h) => h.status === '进行中') || logs[0] || null
  current.value = cur ? await getJson(`/api/handovers/${cur.id}`) : null
  syncPicked()
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
})

function toggle(batchId, ev) {
  if (ev.target.checked) picked[batchId] = picked[batchId] ?? ''
  else delete picked[batchId]
}

async function start() {
  msg.value = ''
  ok.value = false
  try {
    current.value = await postJson('/api/handovers/start', {
      from_shift_id: Number(fromId.value),
      to_shift_id: Number(toId.value),
    })
    ok.value = true
    msg.value = `已开交班单 #${current.value.id}，清单 ${current.value.batch_count} 批`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function saveRejections() {
  if (!current.value) return
  msg.value = ''
  ok.value = false
  try {
    const rejections = Object.entries(picked).map(([bid, reason]) => ({
      batch_id: Number(bid),
      reason: String(reason ?? '').trim(),
    }))
    current.value = await putJson(`/api/handovers/${current.value.id}/rejections`, { rejections })
    ok.value = true
    msg.value = `拒收标记已落库：${rejections.length} 键（独立拒收表，刷新不丢）`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function complete() {
  if (!current.value) return
  msg.value = ''
  ok.value = false
  try {
    current.value = await postJson(`/api/handovers/${current.value.id}/complete`)
    const b = current.value.buckets || {}
    ok.value = current.value.status === '已完成'
    msg.value = current.value.status === '已完成'
      ? `交班单 #${current.value.id} 已完成：过户 ${b.过户数} 键、拒收 ${b.拒收数} 键，分桶证明已落库`
      : `交班单 #${current.value.id} 失败：${current.value.reason || '归属不一致'}`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}
</script>

<template>
  <div>
    <h1>交班办理</h1>
    <p class="lead">
      同一时刻只允许一单进行中；接班方可勾选清单键拒收并写原因（独立拒收表落库）。
      完成时未拒收键过户到接班方、拒收键留在交班方在途，归属变更与拒收落库同一事务整单提交，任一失败整单回滚。
    </p>

    <div class="panel">
      <div class="row">
        <label>交班方
          <select v-model.number="fromId">
            <option v-for="s in shifts" :key="s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}</option>
          </select>
        </label>
        <label>接班方
          <select v-model.number="toId">
            <option v-for="s in shifts" :key="'t'+s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}</option>
          </select>
        </label>
        <button class="btn" :disabled="active" @click="start">发起交班</button>
        <button class="btn ghost" :disabled="!active || !dirty" @click="saveRejections">保存拒收</button>
        <button class="btn ghost" :disabled="!active || dirty" @click="complete">完成交班</button>
      </div>
      <p v-if="active && dirty" class="msg">有未保存的拒收勾选，请先「保存拒收」再完成交班。</p>
      <p class="msg" :class="{ ok }">{{ msg }}</p>
    </div>

    <div class="panel" v-if="current">
      <h2>
        交班单 #{{ current.id }} ·
        <span class="tag" :class="{ on: current.status === '已完成', bad: current.status === '失败' }">
          {{ current.status }}
        </span>
      </h2>
      <p class="lead" style="margin-bottom:12px">
        {{ current.from_shift_name }} → {{ current.to_shift_name }}
        <template v-if="current.status === '失败' && current.reason"> · 失败原因：{{ current.reason }}</template>
      </p>
      <div class="buckets">
        <div class="bucket"><div class="k">清单数</div><div class="v">{{ current.buckets?.清单数 ?? 0 }}</div></div>
        <div class="bucket"><div class="k">过户数</div><div class="v">{{ current.buckets?.过户数 ?? 0 }}</div></div>
        <div class="bucket"><div class="k">拒收数</div><div class="v">{{ current.buckets?.拒收数 ?? 0 }}</div></div>
      </div>
      <div v-if="current.proof" class="panel proof">
        <h2>
          分桶证明
          <span class="tag" :class="{ on: current.proof['一致'], bad: !current.proof['一致'] }">
            {{ current.proof['一致'] ? '一致' : '不一致' }}
          </span>
        </h2>
        <div class="buckets">
          <div class="bucket"><div class="k">纳入</div><div class="v">{{ current.proof.included_count }}</div></div>
          <div class="bucket"><div class="k">拒收</div><div class="v">{{ current.proof.rejected_count }}</div></div>
          <div class="bucket"><div class="k">过户</div><div class="v">{{ current.proof.transferred_count }}</div></div>
          <div class="bucket"><div class="k">交班方在途</div><div class="v">{{ current.proof.from_inflight_count }}</div></div>
          <div class="bucket"><div class="k">接班方在途</div><div class="v">{{ current.proof.to_inflight_count }}</div></div>
        </div>
        <p class="lead" style="margin:0 0 8px">
          纳入键：{{ (current.proof.proof?.纳入键 || []).join('、') || '—' }}
        </p>
        <p class="lead" style="margin:0 0 8px">
          过户键：{{ (current.proof.proof?.过户键 || []).join('、') || '—' }}
        </p>
        <p class="lead" style="margin:0">
          拒收键：{{ (current.proof.proof?.拒收键 || []).join('、') || '—' }}
        </p>
      </div>
      <table>
        <thead>
          <tr>
            <th v-if="active">拒收</th>
            <th>业务键</th><th>标题</th><th>状态</th><th>拒收原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in current.items || []" :key="b.id" :class="{ rejected: active ? picked[b.id] !== undefined : !!reasonOf(b.id) }">
            <td v-if="active">
              <input
                type="checkbox"
                :checked="picked[b.id] !== undefined"
                :aria-label="`拒收 ${b.biz_key}`"
                @change="toggle(b.id, $event)"
              />
            </td>
            <td>{{ b.biz_key }}</td>
            <td>{{ b.title }}</td>
            <td>{{ b.status }}</td>
            <td>
              <template v-if="active">
                <input
                  v-if="picked[b.id] !== undefined"
                  v-model="picked[b.id]"
                  class="reason"
                  placeholder="必填：拒收原因"
                />
                <span v-else class="muted">—</span>
              </template>
              <template v-else>{{ reasonOf(b.id) || '—' }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
