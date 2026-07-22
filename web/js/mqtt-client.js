// mqtt-client.js
// MQTT 客户端封装，基于 paho-mqtt.min.js
// 连接本机 WebSocket 9001，订阅 /G2_minth_status 和 /G2_minth_cloud

const MQTT_BROKER = location.hostname || '10.2.236.6';
const MQTT_PORT   = 9001;
const STATUS_TOPIC = '/G2_minth_status';
const CLOUD_TOPIC  = '/G2_minth_cloud';
const CAMERAS_TOPIC = '/minth/g2/cameras';
const CAMERA_CTRL_TOPIC = '/minth/g2/camera';
const CAMERA_DETECT_TOPIC = '/minth/g2/camera/detect';
const RUNTIME_STEP_TOPIC = '/runtime_step';
const RUNTIME_CODES_TOPIC = '/runtime_codes';
const RUNTIME_PROGRAM_FILES_TOPIC = '/runtime_program_files';
const DATA_REQ_TOPIC = '/minth/g2/data';
const DATA_RESP_TOPIC = '/minth/g2/data/response';
const MAP_POINTS_TOPIC = '/minth/g2/map/points';
const CLOUD_CTRL_TOPIC = '/minth/g2/status';

class MqttClient {
    constructor() {
        this.client = null;
        this.connected = false;
        this.statusCallback = null;
        this.cloudCallbacks = [];
        this.cameraCallbacks = [];
        this.cameraDetectCallbacks = [];
        this.runtimeStepCallbacks = [];
        this.runtimeCodesCallbacks = [];
        this.runtimeProgramFilesCallbacks = [];
        this.dataRespCallbacks = [];
        this.mapPointsCallbacks = [];
    }

    connect() {
        const clientId = 'g2_web_' + Math.random().toString(16).substr(2, 8);
        this.client = new Paho.Client(MQTT_BROKER, MQTT_PORT, clientId);

        this.client.onConnectionLost = (responseObject) => {
            if (responseObject.errorCode !== 0) {
                console.error('[MQTT] 连接丢失:', responseObject.errorMessage);
            }
            this.connected = false;
            // 5 秒后重连
            setTimeout(() => this.connect(), 5000);
        };

        this.client.onMessageArrived = (message) => {
            try {
                const data = JSON.parse(message.payloadString);

                if (message.destinationName === STATUS_TOPIC && this.statusCallback) {
                    this.statusCallback(data);
                } else if (message.destinationName === CLOUD_TOPIC) {
                    // 分发给所有注册的点云回调
                    this.cloudCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === CAMERAS_TOPIC) {
                    // 分发给所有注册的相机回调
                    this.cameraCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === CAMERA_DETECT_TOPIC) {
                    // 分发给所有注册的检测图像回调
                    this.cameraDetectCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === RUNTIME_STEP_TOPIC) {
                    // 分发给所有注册的调试步骤回调
                    this.runtimeStepCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === RUNTIME_CODES_TOPIC) {
                    // 分发给所有注册的代码回调
                    this.runtimeCodesCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === RUNTIME_PROGRAM_FILES_TOPIC) {
                    // 分发给所有注册的程序文件列表回调
                    this.runtimeProgramFilesCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === DATA_RESP_TOPIC) {
                    // 分发给所有注册的数据响应回调
                    this.dataRespCallbacks.forEach(cb => cb(data));
                } else if (message.destinationName === MAP_POINTS_TOPIC) {
                    // 分发给所有注册的地图点位回调
                    this.mapPointsCallbacks.forEach(cb => cb(data));
                }
            } catch (e) {
                console.error('[MQTT] JSON 解析失败:', e);
            }
        };

        this.client.connect({
            onSuccess: () => {
                console.log('[MQTT] 连接成功:', MQTT_BROKER + ':' + MQTT_PORT);
                this.connected = true;
                this.client.subscribe(STATUS_TOPIC, { qos: 0 });
                this.client.subscribe(CLOUD_TOPIC, { qos: 0 });
                this.client.subscribe(CAMERAS_TOPIC, { qos: 0 });
                this.client.subscribe(CAMERA_DETECT_TOPIC, { qos: 0 });
                this.client.subscribe(RUNTIME_STEP_TOPIC, { qos: 0 });
                this.client.subscribe(RUNTIME_CODES_TOPIC, { qos: 0 });
                this.client.subscribe(RUNTIME_PROGRAM_FILES_TOPIC, { qos: 0 });
                this.client.subscribe(DATA_RESP_TOPIC, { qos: 0 });
                this.client.subscribe(MAP_POINTS_TOPIC, { qos: 0 });
            },
            onFailure: (err) => {
                console.error('[MQTT] 连接失败:', err.errorMessage);
                setTimeout(() => this.connect(), 5000);
            },
            useSSL: false,
        });
    }

    onStatus(callback) {
        this.statusCallback = callback;
    }

    /**
     * 注册点云数据回调
     */
    addCloudCallback(callback) {
        if (!this.cloudCallbacks.includes(callback)) {
            this.cloudCallbacks.push(callback);
        }
    }

    /**
     * 移除点云数据回调
     */
    removeCloudCallback(callback) {
        this.cloudCallbacks = this.cloudCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 注册相机数据回调
     */
    addCameraCallback(callback) {
        if (!this.cameraCallbacks.includes(callback)) {
            this.cameraCallbacks.push(callback);
        }
    }

    /**
     * 移除相机数据回调
     */
    removeCameraCallback(callback) {
        this.cameraCallbacks = this.cameraCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 注册检测图像回调
     */
    addCameraDetectCallback(callback) {
        if (!this.cameraDetectCallbacks.includes(callback)) {
            this.cameraDetectCallbacks.push(callback);
        }
    }

    /**
     * 移除检测图像回调
     */
    removeCameraDetectCallback(callback) {
        this.cameraDetectCallbacks = this.cameraDetectCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 发布命令到指定 topic
     */
    publishToTopic(topic, payload) {
        if (!this.connected || !this.client) {
            console.warn('[MQTT] 未连接，无法发送:', topic);
            return;
        }
        const message = new Paho.Message(JSON.stringify(payload));
        message.destinationName = topic;
        message.qos = 0;
        this.client.send(message);
        console.log('[MQTT] 已发送到', topic, payload);
    }

    /**
     * 发布命令到 /G2_minth_app
     * @param {string} cmd - 命令名
     * @param {*} data - 命令数据
     */
    publishCommand(cmd, data) {
        this.publishToTopic('/G2_minth_app', { cmd, data });
    }

    /**
     * 发送相机控制命令
     */
    publishCameraControl(cmd) {
        this.publishToTopic(CAMERA_CTRL_TOPIC, { cmd });
    }

    /**
     * 发送相机控制命令（带额外字段）
     * @param {string} cmd - 命令名
     * @param {object} extra - 额外字段，如 { cameras: [...] } 或 { yolo: 'wxf.pt' }
     */
    publishCameraCommand(cmd, extra = {}) {
        this.publishToTopic(CAMERA_CTRL_TOPIC, { cmd, ...extra });
    }

    /**
     * 注册调试步骤回调
     */
    addRuntimeStepCallback(callback) {
        if (!this.runtimeStepCallbacks.includes(callback)) {
            this.runtimeStepCallbacks.push(callback);
        }
    }

    /**
     * 移除调试步骤回调
     */
    removeRuntimeStepCallback(callback) {
        this.runtimeStepCallbacks = this.runtimeStepCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 注册代码内容回调
     */
    addRuntimeCodesCallback(callback) {
        if (!this.runtimeCodesCallbacks.includes(callback)) {
            this.runtimeCodesCallbacks.push(callback);
        }
    }

    /**
     * 移除代码内容回调
     */
    removeRuntimeCodesCallback(callback) {
        this.runtimeCodesCallbacks = this.runtimeCodesCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 发送 runtime 调试命令
     */
    publishRuntimeDebug(cmd, data) {
        this.publishToTopic('/runtime_debug', { cmd, data });
    }

    /**
     * 注册程序文件列表回调
     */
    addRuntimeProgramFilesCallback(callback) {
        if (!this.runtimeProgramFilesCallbacks.includes(callback)) {
            this.runtimeProgramFilesCallbacks.push(callback);
        }
    }

    /**
     * 移除程序文件列表回调
     */
    removeRuntimeProgramFilesCallback(callback) {
        this.runtimeProgramFilesCallbacks = this.runtimeProgramFilesCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 注册数据响应回调
     */
    addDataRespCallback(callback) {
        if (!this.dataRespCallbacks.includes(callback)) {
            this.dataRespCallbacks.push(callback);
        }
    }

    /**
     * 移除数据响应回调
     */
    removeDataRespCallback(callback) {
        this.dataRespCallbacks = this.dataRespCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 发送数据服务请求
     */
    publishDataReq(cmd, extra = {}) {
        this.publishToTopic(DATA_REQ_TOPIC, { cmd, ...extra });
    }

    /**
     * 注册地图点位回调
     */
    addMapPointsCallback(callback) {
        if (!this.mapPointsCallbacks.includes(callback)) {
            this.mapPointsCallbacks.push(callback);
        }
    }

    /**
     * 移除地图点位回调
     */
    removeMapPointsCallback(callback) {
        this.mapPointsCallbacks = this.mapPointsCallbacks.filter(cb => cb !== callback);
    }

    /**
     * 发送云端控制指令（start_cloud / stop_cloud）
     */
    publishCloudControl(cmd) {
        this.publishToTopic(CLOUD_CTRL_TOPIC, { cmd });
    }
}

export const mqttClient = new MqttClient();
