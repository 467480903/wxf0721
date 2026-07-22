// program-view.js
// 程序视图：显示 main.py 代码，支持读取代码、单步调试、高亮当前执行行

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'ProgramView',
    template: `
    <div class="panel">
        <h5>程序 - main.py</h5>

        <div class="code-block" ref="codeBlock">
            <div
                v-for="(line, idx) in codeLines"
                :key="idx"
                :class="['code-line', { 'code-line-active': idx + 1 === currentLine }]"
                :ref="idx + 1 === currentLine ? 'activeLine' : null"
            >
                <span class="line-num">{{ idx + 1 }}</span>
                <span class="line-content">{{ line || ' ' }}</span>
            </div>
        </div>

        <div class="program-actions">
            <button class="program-btn file-btn" @click="openFileList">文件</button>
            <button class="program-btn read-btn" @click="readCode">读取代码</button>
            <button
                class="program-btn run-btn"
                :class="{ active: running }"
                @click="runProgram">
                {{ running ? '运行中...' : '运行' }}
            </button>
            <button
                class="program-btn debug-btn"
                :class="{ active: debugging }"
                @click="startDebug">
                {{ debugging ? '调试中...' : '单步调试' }}
            </button>
            <button
                class="program-btn next-btn"
                :disabled="!debugging"
                @click="nextLine">
                下一行
            </button>
            <button
                class="program-btn stop-btn"
                @click="stopProgram">
                停止程序
            </button>
        </div>

        <div v-if="currentLine > 0" class="step-info">
            当前执行: 第 <span class="step-line-no">{{ currentLine }}</span> 行
            <span class="step-code">{{ codeLines[currentLine - 1] }}</span>
        </div>

        <!-- 文件列表弹窗 -->
        <div v-if="showFileList" class="save-overlay" @click.self="showFileList = false">
            <div class="save-dialog">
                <h6 style="color:#6cf; margin-bottom:16px;">程序文件</h6>
                <div v-if="programFiles.length === 0" style="color:#888; padding:20px; text-align:center;">
                    暂无文件
                </div>
                <ul v-else class="file-list">
                    <li v-for="f in programFiles" :key="f" @click="selectFile(f)">
                        {{ f }}
                    </li>
                </ul>
                <div class="step-actions">
                    <button class="nav-btn" @click="showFileList = false">关闭</button>
                </div>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            code: '// 点击「读取代码」加载 main.py',
            currentLine: 0,
            debugging: false,
            running: false,
            showFileList: false,
            programFiles: []
        };
    },
    computed: {
        codeLines() {
            return this.code.split('\n');
        }
    },
    watch: {
        currentLine(newVal) {
            if (newVal > 0) {
                this.$nextTick(() => {
                    this.scrollToActiveLine();
                });
            }
        }
    },
    methods: {
        readCode() {
            mqttClient.publishRuntimeDebug('codes');
            console.log('[程序] 已请求读取代码');
        },
        openFileList() {
            // 请求读取 programs 目录下的文件列表
            mqttClient.publishRuntimeDebug('read_program_files');
            this.showFileList = true;
            console.log('[程序] 已请求文件列表');
        },
        selectFile(filename) {
            // 复制选中的文件到 main.py
            mqttClient.publishRuntimeDebug('copy', filename);
            this.showFileList = false;
            console.log('[程序] 已复制', filename, '→ main.py');
            // 复制后自动读取代码
            setTimeout(() => {
                this.readCode();
            }, 500);
        },
        runProgram() {
            if (this.running) return;
            this.running = true;
            this.currentLine = 0;
            mqttClient.publishRuntimeDebug('run');
            console.log('[程序] 已启动运行');
            // 运行超时保护（10 分钟）
            this._runTimer = setTimeout(() => {
                this.running = false;
            }, 600000);
        },
        startDebug() {
            if (this.debugging) return;
            this.debugging = true;
            this.currentLine = 0;
            mqttClient.publishRuntimeDebug('debug');
            console.log('[程序] 已启动单步调试');
            this._debugTimer = setTimeout(() => {
                this.debugging = false;
            }, 60000);
        },
        nextLine() {
            if (!this.debugging) return;
            mqttClient.publishRuntimeDebug('next');
            console.log('[程序] 下一行');
        },
        stopProgram() {
            mqttClient.publishRuntimeDebug('stop');
            this.debugging = false;
            this.running = false;
            this.currentLine = 0;
            if (this._debugTimer) clearTimeout(this._debugTimer);
            if (this._runTimer) clearTimeout(this._runTimer);
            console.log('[程序] 已请求停止');
        },
        onStep(data) {
            if (data && data.lineno) {
                console.log('[程序] 步骤:', data.lineno, data.code);
                this.currentLine = data.lineno;
            }
        },
        onCodes(data) {
            if (data && data.code !== undefined) {
                this.code = data.code;
                console.log('[程序] 已加载代码', data.code.length, '字符');
            }
        },
        onProgramFiles(data) {
            if (data && data.files) {
                this.programFiles = data.files;
                console.log('[程序] 收到文件列表:', data.files);
            }
        },
        scrollToActiveLine() {
            const el = this.$refs.activeLine;
            if (el && el.length > 0) {
                el[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    },
    mounted() {
        mqttClient.addRuntimeStepCallback(this.onStep);
        mqttClient.addRuntimeCodesCallback(this.onCodes);
        mqttClient.addRuntimeProgramFilesCallback(this.onProgramFiles);
    },
    beforeUnmount() {
        mqttClient.removeRuntimeStepCallback(this.onStep);
        mqttClient.removeRuntimeCodesCallback(this.onCodes);
        mqttClient.removeRuntimeProgramFilesCallback(this.onProgramFiles);
        if (this._debugTimer) clearTimeout(this._debugTimer);
        if (this._runTimer) clearTimeout(this._runTimer);
    }
};
