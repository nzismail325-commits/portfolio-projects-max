<template>
  <div class="compose-section">
    <div class="compose-card">
      <div class="compose-header">
        <h3 class="compose-title">
          <el-icon><EditPen /></el-icon>
          发送邮件给学生
        </h3>
        <el-button 
          text 
          circle 
          @click="$emit('close')"
          class="close-btn"
        >
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
      
      <el-form :model="composeForm" :label-width="'100px'" class="compose-form">
        <!-- 发送方式选择 -->
        <div class="send-type-section">
          <div class="section-label">
            <span class="required-mark">*</span>
            <span>发送方式</span>
          </div>
          <div class="send-type-cards">
            <div 
              v-for="type in sendTypeOptions" 
              :key="type.value"
              :class="['send-type-card', { 'active': composeForm.sendType === type.value }]"
              @click="composeForm.sendType = type.value; handleSendTypeChange()"
            >
              <div class="card-icon">
                <el-icon :size="24"><component :is="type.icon" /></el-icon>
              </div>
              <div class="card-label">{{ type.label }}</div>
            </div>
          </div>
        </div>

        <!-- 收件人选择区域 -->
        <div class="form-section">
          <!-- 单个发送 -->
          <div v-if="composeForm.sendType === 'SINGLE'" class="receiver-section">
            <div class="section-label">
              <span class="required-mark">*</span>
              <span>选择学生</span>
            </div>
            <el-select
              v-model="composeForm.receiverIds"
              placeholder="请选择学生"
              filterable
              remote
              :remote-method="searchStudents"
              :loading="searchingStudents"
              style="width: 100%"
              clearable
              :multiple="false"
            >
              <el-option
                v-for="student in studentList"
                :key="student.id"
                :label="`${student.name} (${student.studentId})`"
                :value="student.id"
              />
            </el-select>
          </div>

          <!-- 批量选择 -->
          <div v-if="composeForm.sendType === 'BATCH'" class="receiver-section">
            <div class="section-label-row">
              <div class="section-label">
                <span class="required-mark">*</span>
                <span>选择学生</span>
              </div>
              <div class="batch-actions">
                <el-button 
                  text 
                  type="primary" 
                  size="small"
                  @click="selectAllStudents"
                  :disabled="filteredStudentList.length === 0"
                >
                  <el-icon><Select /></el-icon>
                  全选
                </el-button>
                <el-button 
                  text 
                  type="info" 
                  size="small"
                  @click="clearAllStudents"
                  :disabled="composeForm.receiverIds.length === 0"
                >
                  <el-icon><Close /></el-icon>
                  取消全选
                </el-button>
                <el-tag v-if="composeForm.receiverIds.length > 0" type="success" size="small">
                  已选择 {{ composeForm.receiverIds.length }} 人
                </el-tag>
              </div>
            </div>
            <el-select
              v-model="composeForm.receiverIds"
              placeholder="请选择多个学生（支持搜索）"
              filterable
              remote
              multiple
              :remote-method="searchStudents"
              :loading="searchingStudents"
              style="width: 100%"
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="3"
            >
              <el-option
                v-for="student in filteredStudentList"
                :key="student.id"
                :label="`${student.name} (${student.studentId})`"
                :value="student.id"
              />
            </el-select>
          </div>

          <!-- 按年级 -->
          <div v-if="composeForm.sendType === 'GRADE'" class="receiver-section">
            <div class="section-label">
              <span class="required-mark">*</span>
              <span>选择年级</span>
            </div>
            <el-select
              v-model="composeForm.filterValue"
              placeholder="请选择年级（支持搜索）"
              filterable
              remote
              :remote-method="searchGrades"
              :loading="loadingGrades"
              style="width: 100%"
              clearable
            >
              <el-option
                v-for="grade in gradeList"
                :key="grade.grade"
                :label="grade.displayName"
                :value="grade.grade.substring(2)"
              />
            </el-select>
            <div v-if="composeForm.filterValue" class="form-tip">
              <el-icon><InfoFilled /></el-icon>
              将发送给所有学号以"20{{ composeForm.filterValue }}"开头的学生
            </div>
          </div>

          <!-- 按班级 -->
          <div v-if="composeForm.sendType === 'CLASS'" class="receiver-section">
            <div class="section-label">
              <span class="required-mark">*</span>
              <span>选择班级</span>
            </div>
            <el-select
              v-model="composeForm.filterValue"
              placeholder="请选择班级（支持搜索）"
              filterable
              remote
              :remote-method="searchClasses"
              :loading="loadingClasses"
              style="width: 100%"
              clearable
            >
              <el-option-group
                v-for="group in groupedClassList"
                :key="group.grade"
                :label="group.gradeLabel"
              >
                <el-option
                  v-for="classItem in group.classes"
                  :key="`${classItem.grade}-${classItem.className}`"
                  :label="classItem.className"
                  :value="classItem.className"
                />
              </el-option-group>
            </el-select>
          </div>
        </div>

        <!-- 邮件主题和内容 -->
        <div class="form-section">
          <el-form-item label="邮件主题" required>
            <el-input
              v-model="composeForm.title"
              placeholder="请输入邮件主题"
              maxlength="200"
              show-word-limit
            />
          </el-form-item>
          <el-form-item label="邮件内容" required>
            <el-input
              v-model="composeForm.content"
              type="textarea"
              :rows="8"
              placeholder="请输入邮件内容"
              maxlength="2000"
              show-word-limit
              resize="vertical"
            />
          </el-form-item>
        </div>

        <!-- 操作按钮 -->
        <div class="form-actions">
          <el-button @click="handleReset">
            <el-icon><RefreshLeft /></el-icon>
            重置
          </el-button>
          <el-button type="primary" :loading="sending" @click="handleSend">
            <el-icon v-if="!sending"><Promotion /></el-icon>
            发送邮件
          </el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  EditPen,
  Close,
  User,
  UserFilled,
  School,
  OfficeBuilding,
  Select,
  Promotion,
  RefreshLeft,
  InfoFilled
} from '@element-plus/icons-vue'
import { sendMail as sendMailApi, getStudentList, getGradeList, getClassList } from '@/api/notification'

// 定义事件
const emit = defineEmits(['close', 'success'])

// 发送状态
const sending = ref(false)
const searchingStudents = ref(false)
const loadingGrades = ref(false)
const loadingClasses = ref(false)

// 学生列表（用于搜索和选择）
const studentList = ref([])
// 所有学生列表（用于全选功能）
const allStudentList = ref([])

// 年级列表
const gradeList = ref([])
// 班级列表
const classList = ref([])

// 发送方式选项配置
const sendTypeOptions = [
  { value: 'SINGLE', label: '单个发送', icon: User },
  { value: 'BATCH', label: '批量选择', icon: UserFilled },
  { value: 'GRADE', label: '按年级', icon: School },
  { value: 'CLASS', label: '按班级', icon: OfficeBuilding }
]

// 按年级分组的班级列表
const groupedClassList = computed(() => {
  const groups = new Map()
  
  classList.value.forEach(classItem => {
    const grade = classItem.grade || '未知年级'
    const gradeLabel = grade ? `${grade}级` : '未知年级'
    
    if (!groups.has(grade)) {
      groups.set(grade, {
        grade,
        gradeLabel,
        classes: []
      })
    }
    
    groups.get(grade).classes.push(classItem)
  })
  
  // 转换为数组并按年级降序排序
  return Array.from(groups.values()).sort((a, b) => {
    return b.grade.localeCompare(a.grade)
  })
})

// 写邮件表单
const composeForm = reactive({
  sendType: 'SINGLE',
  receiverIds: [],
  filterValue: '',
  title: '',
  content: ''
})

// 搜索学生
const searchStudents = async (keyword) => {
  if (!keyword || keyword.trim() === '') {
    studentList.value = []
    allStudentList.value = []
    return
  }
  
  searchingStudents.value = true
  try {
    const res = await getStudentList({ keyword: keyword.trim() })
    if (res.code === 200 && res.data) {
      studentList.value = res.data || []
      allStudentList.value = res.data || []
    } else {
      studentList.value = []
      allStudentList.value = []
    }
  } catch (error) {
    console.error('搜索学生失败:', error)
    studentList.value = []
    allStudentList.value = []
  } finally {
    searchingStudents.value = false
  }
}

// 过滤后的学生列表（用于批量选择）
const filteredStudentList = computed(() => {
  return studentList.value
})

// 全选学生
const selectAllStudents = () => {
  if (filteredStudentList.value.length === 0) {
    ElMessage.warning('请先搜索学生')
    return
  }
  const allIds = filteredStudentList.value.map(s => s.id)
  // 合并已选和当前列表，去重
  composeForm.receiverIds = [...new Set([...composeForm.receiverIds, ...allIds])]
  ElMessage.success(`已选择 ${composeForm.receiverIds.length} 名学生`)
}

// 取消全选
const clearAllStudents = () => {
  if (composeForm.receiverIds.length === 0) {
    ElMessage.info('当前没有选中的学生')
    return
  }
  composeForm.receiverIds = []
  ElMessage.info('已取消全选')
}

// 发送方式变化
const handleSendTypeChange = () => {
  composeForm.receiverIds = []
  composeForm.filterValue = ''
  studentList.value = []
  allStudentList.value = []
  
  // 如果切换到年级或班级模式，加载对应的列表
  if (composeForm.sendType === 'GRADE') {
    loadGradeList()
  } else if (composeForm.sendType === 'CLASS') {
    loadClassList()
  }
}

// 加载年级列表
const loadGradeList = async () => {
  if (gradeList.value.length > 0) return // 已加载过，不再重复加载
  
  loadingGrades.value = true
  try {
    const res = await getGradeList()
    if (res.code === 200 && res.data) {
      gradeList.value = res.data.grades || []
    }
  } catch (error) {
    console.error('加载年级列表失败:', error)
  } finally {
    loadingGrades.value = false
  }
}

// 搜索年级（用于远程搜索）
const searchGrades = async (keyword) => {
  if (!keyword || keyword.trim() === '') {
    await loadGradeList()
    return
  }
  
  loadingGrades.value = true
  try {
    const res = await getGradeList()
    if (res.code === 200 && res.data) {
      const keywordLower = keyword.trim().toLowerCase()
      gradeList.value = (res.data.grades || []).filter(grade => 
        grade.grade.toLowerCase().includes(keywordLower) ||
        grade.displayName.toLowerCase().includes(keywordLower)
      )
    }
  } catch (error) {
    console.error('搜索年级失败:', error)
  } finally {
    loadingGrades.value = false
  }
}

// 加载班级列表
const loadClassList = async (keyword = '') => {
  loadingClasses.value = true
  try {
    const res = await getClassList({ keyword })
    if (res.code === 200 && res.data) {
      classList.value = res.data.classes || []
    }
  } catch (error) {
    console.error('加载班级列表失败:', error)
  } finally {
    loadingClasses.value = false
  }
}

// 搜索班级（用于远程搜索）
const searchClasses = async (keyword) => {
  await loadClassList(keyword)
}

// 发送邮件
const handleSend = async () => {
  // 验证表单
  if (composeForm.sendType === 'SINGLE' || composeForm.sendType === 'BATCH') {
    if (!composeForm.receiverIds || composeForm.receiverIds.length === 0) {
      ElMessage.warning('请选择收件人')
      return
    }
  } else {
    if (!composeForm.filterValue || !composeForm.filterValue.trim()) {
      ElMessage.warning(`请输入${composeForm.sendType === 'GRADE' ? '年级' : '班级'}`)
      return
    }
  }
  
  if (!composeForm.title || !composeForm.title.trim()) {
    ElMessage.warning('请输入邮件主题')
    return
  }
  
  if (!composeForm.content || !composeForm.content.trim()) {
    ElMessage.warning('请输入邮件内容')
    return
  }
  
  sending.value = true
  try {
    const requestData = {
      sendType: composeForm.sendType,
      title: composeForm.title,
      content: composeForm.content
    }
    
    if (composeForm.sendType === 'SINGLE' || composeForm.sendType === 'BATCH') {
      // 单个发送时，receiverIds 可能是单个值，需要转换为数组
      requestData.receiverIds = composeForm.sendType === 'SINGLE' 
        ? (Array.isArray(composeForm.receiverIds) ? composeForm.receiverIds : [composeForm.receiverIds])
        : composeForm.receiverIds
    } else if (composeForm.sendType === 'GRADE') {
      // 年级模式：发送完整的4位年级（如"2021"）
      requestData.filterValue = composeForm.filterValue ? '20' + composeForm.filterValue : ''
    } else {
      // 班级模式：直接发送班级名称
      requestData.filterValue = composeForm.filterValue
    }
    
    const res = await sendMailApi(requestData)
    if (res.code === 200) {
      ElMessage.success(res.data?.message || '邮件发送成功')
      handleReset()
      emit('success')
      emit('close')
    } else {
      ElMessage.error(res.message || '发送邮件失败')
    }
  } catch (error) {
    console.error('发送邮件失败:', error)
    ElMessage.error('发送邮件失败')
  } finally {
    sending.value = false
  }
}

// 重置表单
const handleReset = () => {
  composeForm.sendType = 'SINGLE'
  composeForm.receiverIds = []
  composeForm.filterValue = ''
  composeForm.title = ''
  composeForm.content = ''
  studentList.value = []
  allStudentList.value = []
}
</script>

<style scoped>
/* 邮件编写区域 */
.compose-section {
  margin-bottom: 24px;
}

.compose-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.compose-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

.compose-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.compose-title .el-icon {
  color: #26a69a;
}

.close-btn {
  color: #909399;
}

.close-btn:hover {
  color: #303133;
}

.compose-form {
  max-width: 100%;
}

.form-section {
  margin-bottom: 20px;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 12px;
}

.section-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.required-mark {
  color: #f56c6c;
  font-weight: 600;
}

/* 发送方式选择区域 */
.send-type-section {
  margin-bottom: 20px;
}

.send-type-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.send-type-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px 16px;
  background: #ffffff;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.send-type-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(38, 166, 154, 0.05) 0%, rgba(0, 137, 123, 0.05) 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.send-type-card:hover {
  border-color: #26a69a;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(38, 166, 154, 0.15);
}

.send-type-card:hover::before {
  opacity: 1;
}

.send-type-card.active {
  border-color: #26a69a;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  color: #ffffff;
  box-shadow: 0 6px 20px rgba(38, 166, 154, 0.3);
  transform: translateY(-2px);
}

.send-type-card.active::before {
  opacity: 0;
}

.send-type-card.active .card-icon {
  color: #ffffff;
}

.send-type-card.active .card-label {
  color: #ffffff;
}

.card-icon {
  margin-bottom: 8px;
  color: #26a69a;
  transition: all 0.3s ease;
}

.send-type-card.active .card-icon {
  transform: scale(1.1);
}

.card-label {
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  transition: color 0.3s ease;
}

.send-type-card:hover .card-label {
  color: #26a69a;
}

.receiver-section {
  margin-bottom: 12px;
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
  border-left: 3px solid #26a69a;
}

.form-tip .el-icon {
  color: #26a69a;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid #f0f0f0;
}

.form-actions .el-button {
  min-width: 120px;
}

/* 表单输入框样式优化 */
.compose-form :deep(.el-input__wrapper) {
  border-radius: 8px;
  transition: all 0.3s ease;
}

.compose-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #26a69a inset;
}

.compose-form :deep(.el-input.is-focus .el-input__wrapper) {
  box-shadow: 0 0 0 1px #26a69a inset;
}

.compose-form :deep(.el-textarea__inner) {
  border-radius: 8px;
  transition: all 0.3s ease;
}

.compose-form :deep(.el-textarea__inner:hover) {
  border-color: #26a69a;
}

.compose-form :deep(.el-textarea__inner:focus) {
  border-color: #26a69a;
}

.compose-form :deep(.el-select) {
  width: 100%;
}

.compose-form :deep(.el-select__wrapper) {
  border-radius: 8px;
  transition: all 0.3s ease;
}

.compose-form :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px #26a69a inset;
}

.compose-form :deep(.el-select.is-focused .el-select__wrapper) {
  box-shadow: 0 0 0 1px #26a69a inset;
}

/* 班级选择器分组样式 */
.compose-form :deep(.el-select-group__title) {
  font-size: 13px;
  font-weight: 600;
  color: #26a69a;
  padding: 8px 12px;
  background: #f0f9ff;
  border-bottom: 1px solid #e0f2fe;
}

.compose-form :deep(.el-select-group__wrap:not(:last-of-type)) {
  border-bottom: 1px solid #f0f0f0;
}

.compose-form :deep(.el-select-group__wrap .el-select-dropdown__item) {
  padding-left: 24px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .send-type-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .compose-card {
    padding: 16px;
  }
  
  .compose-form {
    label-width: 80px;
  }
  
  .send-type-cards {
    grid-template-columns: 1fr;
  }
  
  .section-label-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .batch-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  
  .form-actions {
    flex-direction: column;
  }
  
  .form-actions .el-button {
    width: 100%;
  }
}
</style>

