import json
import os
import random
import threading
import time
import subprocess
import shutil
from datetime import datetime
import platform
import sys
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FSGSystem:
    def __init__(self):
        self.current_session = None
        self.server_process = None
        self.log_monitor = None
        self.monitor_interval = 5
        self.penalty_seconds = 30
        self.is_monitoring = False
        self.last_log_file = None
        self.increased_drop_rate = False
        self.pure_trial_bonus = 0

        # 消息队列
        self.message_queue = []
        self.max_messages = 100

        # 60秒关闭计时器
        self.shutdown_timer = None
        self.is_shutting_down = False

        # 线程锁
        self.lock = threading.Lock()

        # 目标物品
        self.target_item = "minecraft:dragon_egg"

        # 关键：根据实际文件结构调整服务器路径
        # 获取当前脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 脚本在 main 目录中，服务器在上一级的 bedrock-server-1.16.10.02 目录
        self.server_dir = os.path.join(os.path.dirname(script_dir), "bedrock-server-1.16.10.02")

        # 服务器相关文件路径
        self.server_properties = os.path.join(self.server_dir, "server.properties")
        self.bedrock_server_exe = os.path.join(self.server_dir, "bedrock_server.exe")
        self.world_dir = os.path.join(self.server_dir, "worlds")
        self.server_log_file = os.path.join(self.server_dir, "logs", "latest.log")

        # 世界数据库路径
        self.world_db_path = os.path.join(self.world_dir, "Bedrock level", "db")

        # FSG资源路径 - 这些在 main 目录中
        self.mclog_dir = "mclog"  # 当前目录下的 mclog
        self.fsg_resource_dir = "FSG_resource"  # 当前目录下的 FSG_resource
        self.fsg_resource_packed_dir = "FSG_resource_packed"  # 当前目录下的 FSG_resource_packed

        # 确保目录存在
        os.makedirs(self.mclog_dir, exist_ok=True)

        # 配置文件 - 在当前目录下
        self.config_file = "fsg_config.json"
        self.scores_file = "fsg_scores.json"

        # ========== 段位系统定义保持不变 ==========
        self.ranks = [
            {"name": "木头III", "min_score": 0, "level": 3, "type": "wood", "interval": 10},
            {"name": "木头II", "min_score": 10, "level": 2, "type": "wood", "interval": 10},
            {"name": "木头I", "min_score": 20, "level": 1, "type": "wood", "interval": 10},
            {"name": "石头III", "min_score": 30, "level": 3, "type": "stone", "interval": 10},
            {"name": "石头II", "min_score": 40, "level": 2, "type": "stone", "interval": 10},
            {"name": "石头I", "min_score": 50, "level": 1, "type": "stone", "interval": 10},
            {"name": "铜III", "min_score": 60, "level": 3, "type": "copper", "interval": 20},
            {"name": "铜II", "min_score": 80, "level": 2, "type": "copper", "interval": 20},
            {"name": "铜I", "min_score": 100, "level": 1, "type": "copper", "interval": 20},
            {"name": "铁III", "min_score": 120, "level": 3, "type": "iron", "interval": 20},
            {"name": "铁II", "min_score": 140, "level": 2, "type": "iron", "interval": 20},
            {"name": "铁I", "min_score": 160, "level": 1, "type": "iron", "interval": 20},
            {"name": "金V", "min_score": 180, "level": 5, "type": "gold", "interval": 30},
            {"name": "金IV", "min_score": 210, "level": 4, "type": "gold", "interval": 30},
            {"name": "金III", "min_score": 240, "level": 3, "type": "gold", "interval": 30},
            {"name": "金II", "min_score": 270, "level": 2, "type": "gold", "interval": 30},
            {"name": "金I", "min_score": 300, "level": 1, "type": "gold", "interval": 30},
            {"name": "钻石V", "min_score": 330, "level": 5, "type": "diamond", "interval": 30},
            {"name": "钻石IV", "min_score": 360, "level": 4, "type": "diamond", "interval": 30},
            {"name": "钻石III", "min_score": 390, "level": 3, "type": "diamond", "interval": 30},
            {"name": "钻石II", "min_score": 420, "level": 2, "type": "diamond", "interval": 30},
            {"name": "钻石I", "min_score": 450, "level": 1, "type": "diamond", "interval": 30},
            {"name": "下界合金", "min_score": 480, "level": 1, "type": "netherite", "interval": 30}
        ]

        self.rank_symbols = {
            "wood": "🪵",
            "stone": "🪨",
            "copper": "🔶",
            "iron": "⚙️",
            "gold": "⭐",
            "diamond": "💎",
            "netherite": "🔥"
        }

        # ========== 时间加分规则保持不变 ==========
        self.time_bonus_rules = {
            "wood_stone": {"30": 1, "25": 2, "20": 4, "18": 6, "15": 10, "12": 15},
            "copper_iron": {"25": 1, "20": 2, "18": 3, "16": 5, "14": 8, "12": 10},
            "gold_diamond_netherite": {"20": 1, "15": 2, "12": 3, "10": 4, "8": 6, "7": 8}
        }

        # 村庄加分规则
        self.village_bonus_gold_plus = {
            "平原村": 0,
            "沙漠村": 1,
            "雪原村": 1,
            "云杉村": 0,
            "金合欢村": 0,
            "未知类型": 0
        }

        self.village_bonus_normal = {
            "平原村": 0,
            "沙漠村": 1,
            "雪原村": 2,
            "云杉村": 1,
            "金合欢村": 2,
            "未知类型": 0
        }

        # 加载配置和成绩
        self.load_config()
        self.load_scores()

        # 添加调试信息，确认路径正确
        self.add_message(f"脚本目录: {script_dir}")
        self.add_message(f"服务器目录: {self.server_dir}")
        self.add_message(f"server.properties路径: {self.server_properties}")
        self.add_message(f"bedrock_server.exe路径: {self.bedrock_server_exe}")
        self.add_message(f"服务器目录是否存在: {os.path.exists(self.server_dir)}")
        self.add_message(f"server.properties是否存在: {os.path.exists(self.server_properties)}")

    def add_message(self, message, msg_type="info"):
        """添加消息到队列，替代原来的gui_callback"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}"

        with self.lock:
            self.message_queue.append({
                "time": timestamp,
                "message": message,
                "type": msg_type
            })

            # 保持队列长度
            if len(self.message_queue) > self.max_messages:
                self.message_queue = self.message_queue[-self.max_messages:]

        logger.info(formatted_msg)

    def get_messages(self, last_n=20):
        """获取最近的消息"""
        with self.lock:
            return self.message_queue[-last_n:] if self.message_queue else []

    def load_config(self):
        """加载配置"""
        default_config = {
            "minecraft_path": "",
            "monitor_interval": 5,
            "penalty_seconds": 30,
            "program_version": "1.0.0"
        }

        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if isinstance(config, dict):
                        self.config = config
                        self.monitor_interval = config.get("monitor_interval", self.monitor_interval)
                        self.penalty_seconds = config.get("penalty_seconds", self.penalty_seconds)
                    else:
                        self.config = default_config.copy()
            else:
                self.config = default_config.copy()
                self.save_config()
        except Exception as e:
            self.add_message(f"加载配置时出错: {e}", "error")
            self.config = default_config.copy()

    def load_scores(self):
        """加载成绩"""
        default_scores = {
            "scores": [],
            "total_score": 0,
            "current_rank": "木头III",
            "rank_progress": 0,
            "rank_stars": 0,
            "best_time": None,
            "best_seed": None,
            "best_village_type": None,
            "total_attempts": 0,
            "successful_attempts": 0,
            "top_scores": [],
            "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            if os.path.exists(self.scores_file):
                with open(self.scores_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    self.add_message("成绩文件格式错误，使用默认值", "warning")
                    self.scores_data = default_scores.copy()
                    return

                self.scores_data = default_scores.copy()
                for key in default_scores:
                    if key in data:
                        if key in ["scores", "top_scores"]:
                            if isinstance(data[key], list):
                                self.scores_data[key] = [
                                    item for item in data[key]
                                    if isinstance(item, dict)
                                ]
                            else:
                                self.scores_data[key] = []
                        else:
                            self.scores_data[key] = data[key]

                # 确保数值类型的正确性
                for key in ["total_score", "total_attempts", "successful_attempts", "rank_progress", "rank_stars"]:
                    if not isinstance(self.scores_data[key], (int, float)):
                        self.scores_data[key] = 0

                # 确保current_rank是字符串且在ranks列表中
                if not isinstance(self.scores_data["current_rank"], str):
                    self.scores_data["current_rank"] = "木头III"
                elif self.scores_data["current_rank"] not in [r["name"] for r in self.ranks]:
                    self.scores_data["current_rank"] = "木头III"

            else:
                self.add_message("未找到成绩文件，创建默认成绩", "info")
                self.scores_data = default_scores.copy()
                self.save_scores()

        except Exception as e:
            self.add_message(f"加载成绩时出错: {e}", "error")
            self.scores_data = default_scores.copy()

    def save_config(self):
        """保存配置"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.add_message(f"保存配置时出错: {e}", "error")
            return False

    def save_scores(self):
        """保存成绩"""
        with self.lock:
            try:
                if not isinstance(self.scores_data, dict):
                    self.add_message("scores_data不是字典，重置为默认值", "error")
                    self.load_scores()

                # 验证并清理数据
                cleaned_data = {}
                default_keys = {
                    "scores": [],
                    "total_score": 0,
                    "current_rank": "木头III",
                    "rank_progress": 0,
                    "rank_stars": 0,
                    "best_time": None,
                    "best_seed": None,
                    "best_village_type": None,
                    "total_attempts": 0,
                    "successful_attempts": 0,
                    "top_scores": [],
                    "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                for key in default_keys:
                    if key in self.scores_data:
                        cleaned_data[key] = self.scores_data[key]
                    else:
                        cleaned_data[key] = default_keys[key]

                # 确保scores和top_scores是列表且元素是字典
                for list_key in ["scores", "top_scores"]:
                    if not isinstance(cleaned_data[list_key], list):
                        cleaned_data[list_key] = []
                    else:
                        cleaned_data[list_key] = [
                            item for item in cleaned_data[list_key]
                            if isinstance(item, dict)
                        ]

                # 更新最后修改时间
                cleaned_data["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 保存到文件
                with open(self.scores_file, "w", encoding="utf-8") as f:
                    json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

                self.add_message(f"成绩已保存到 {self.scores_file}", "info")
                return True

            except Exception as e:
                self.add_message(f"保存成绩时出错: {e}", "error")
                return False

    def get_village_bonus(self, village_type, rank_type):
        """根据段位类型获取村庄加分"""
        if rank_type in ["gold", "diamond", "netherite"]:
            # 金以上段位使用新规则
            return self.village_bonus_gold_plus.get(village_type, 0)
        else:
            # 金以下段位使用原规则
            return self.village_bonus_normal.get(village_type, 0)

    def format_time_display(self, seconds):
        """格式化时间显示为 mm:ss"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def stop_server(self):
        """强制关闭服务器"""
        try:
            if self.server_process and self.server_process.poll() is None:
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.server_process.kill()
                self.server_process = None

            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "bedrock_server.exe"],
                               capture_output=True)
        except Exception as e:
            self.add_message(f"停止服务器时出错: {e}", "error")

    def clear_world_files(self):
        """清空世界文件"""
        try:
            bedrock_level_dir = os.path.join(self.world_dir, "Bedrock level")

            if os.path.exists(bedrock_level_dir):
                self.add_message(f"清理Bedrock level文件夹: {bedrock_level_dir}")
                for item in os.listdir(bedrock_level_dir):
                    item_path = os.path.join(bedrock_level_dir, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.unlink(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        self.add_message(f"删除{item}时出错: {e}", "warning")
            else:
                self.add_message(f"Bedrock level文件夹不存在，创建: {bedrock_level_dir}")
                os.makedirs(bedrock_level_dir, exist_ok=True)

            return True
        except Exception as e:
            self.add_message(f"清理世界文件时出错: {e}", "error")
            return False

    def copy_fsg_resources(self):
        """复制FSG资源文件夹中的资源到Bedrock level文件夹"""
        try:
            source_dir = self.fsg_resource_packed_dir if self.increased_drop_rate else self.fsg_resource_dir

            if not os.path.exists(source_dir):
                self.add_message(f"{source_dir}文件夹不存在", "error")
                return False

            bedrock_level_dir = os.path.join(self.world_dir, "Bedrock level")
            os.makedirs(bedrock_level_dir, exist_ok=True)

            for item in os.listdir(source_dir):
                src_path = os.path.join(source_dir, item)
                dst_path = os.path.join(bedrock_level_dir, item)

                try:
                    if os.path.isfile(src_path):
                        shutil.copy2(src_path, dst_path)
                    elif os.path.isdir(src_path):
                        if os.path.exists(dst_path):
                            shutil.rmtree(dst_path)
                        shutil.copytree(src_path, dst_path)
                except Exception as e:
                    self.add_message(f"复制{item}时出错: {e}", "warning")
                    continue

            self.add_message(f"FSG资源复制完成，使用资源包: {'掉率增加' if self.increased_drop_rate else '正常掉率'}")
            return True
        except Exception as e:
            self.add_message(f"复制FSG资源时出错: {e}", "error")
            return False

    def generate_seed(self):
        """从5个种子文件中随机选择一个种子"""
        seed_files = {
            "seed0.txt": "平原村",
            "seed1.txt": "沙漠村",
            "seed2.txt": "雪原村",
            "seed3.txt": "云杉村",
            "seed4.txt": "金合欢村"
        }

        selected_file = random.choice(list(seed_files.keys()))
        village_type = seed_files[selected_file]

        try:
            with open(selected_file, 'r') as f:
                seeds = [line.strip() for line in f.readlines() if line.strip()]

            if not seeds:
                raise ValueError(f"种子文件 {selected_file} 为空")

            selected_seed = random.choice(seeds)

            self.add_message(f"从 {selected_file} 中选择种子: {selected_seed}")
            self.add_message(f"村庄类型: {village_type}")

            return selected_seed, village_type

        except Exception as e:
            self.add_message(f"读取种子文件失败: {e}", "error")
            backup_seed = 564030617
            return backup_seed, "未知类型"

    def update_seed_in_properties(self, seed):
        """修改server.properties中的种子"""
        try:
            if not os.path.exists(self.server_properties):
                self.add_message("server.properties不存在，创建新文件")
                return self.create_default_server_properties(seed)

            with open(self.server_properties, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            seed_line_index = -1
            for i, line in enumerate(lines):
                if line.strip().startswith('level-seed='):
                    seed_line_index = i
                    break

            if seed_line_index != -1:
                lines[seed_line_index] = f'level-seed={seed}\n'
            else:
                lines.append(f'\nlevel-seed={seed}\n')

            with open(self.server_properties, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            self.add_message("已成功更新服务器种子")
            return True

        except Exception as e:
            self.add_message(f"更新服务器种子失败: {e}", "error")
            return False

    def create_default_server_properties(self, seed):
        """创建默认的server.properties文件"""
        try:
            default_properties = [
                "server-name=Dedicated Server",
                "# Used as the server name",
                "# Allowed values: Any string",
                "",
                "gamemode=survival",
                "# Sets the game mode for new players.",
                "# Allowed values: \"survival\", \"creative\", or \"adventure\"",
                "",
                "difficulty=easy",
                "# Sets the difficulty of the world.",
                "# Allowed values: \"peaceful\", \"easy\", \"normal\", or \"hard\"",
                "",
                "allow-cheats=false",
                "# If true then cheats like commands can be used.",
                "# Allowed values: \"true\" or \"false\"",
                "",
                "max-players=10",
                "# The maximum number of players that can play on the server.",
                "# Allowed values: Any positive integer",
                "",
                "online-mode=true",
                "# If true then all connected players must be authenticated to Xbox Live.",
                "# Clients connecting to remote (non-LAN) servers will always require Xbox Live authentication regardless of this setting.",
                "# If the server accepts connections from the Internet, then it's highly recommended to enable online-mode.",
                "# Allowed values: \"true\" or \"false\"",
                "",
                "white-list=false",
                "# If true then all connected players must be listed in the separate whitelist.json file.",
                "# Allowed values: \"true\" or \"false\"",
                "",
                "server-port=19132",
                "# Which IPv4 port the server should listen to.",
                "# Allowed values: Integers in the range [1, 65535]",
                "",
                "server-portv6=19133",
                "# Which IPv6 port the server should listen to.",
                "# Allowed values: Integers in the range [1, 65535]",
                "",
                "view-distance=64",
                "# The maximum allowed view distance in number of chunks.",
                "# Allowed values: Any positive integer.",
                "",
                "tick-distance=4",
                "# The world will be ticked this many chunks away from any player.",
                "# Allowed values: Integers in the range [4, 12]",
                "",
                "player-idle-timeout=30",
                "# After a player has idled for this many minutes they will be kicked. If set to 0 then players can idle indefinitely.",
                "# Allowed values: Any non-negative integer.",
                "",
                "max-threads=8",
                "# Maximum number of threads the server will try to use. If set to 0 or removed then it will use as many as possible.",
                "# Allowed values: Any positive integer.",
                "",
                f"level-name=Bedrock level",
                "# Allowed values: Any string",
                "",
                f"level-seed={seed}",
                "# Use to randomize the world",
                "# Allowed values: Any string",
                "",
                "default-player-permission-level=member",
                "# Permission level for new players joining for the first time.",
                "# Allowed values: \"visitor\", \"member\", \"operator\"",
                "",
                "texturepack-required=false",
                "# Force clients to use texture packs in the current world",
                "# Allowed values: \"true\" or \"false\"",
                "",
                "content-log-file-enabled=false",
                "# Enables logging content errors to a file",
                "# Allowed values: \"true\" or \"false\"",
                "",
                "compression-threshold=1",
                "# Determines the smallest size of raw network payload to compress",
                "# Allowed values: 0-65535",
                "",
                "server-authoritative-movement=true",
                "# Enables server authoritative movement. If true, the server will replay local user input on",
                "# the server and send down corrections when the client's position doesn't match the server's.",
                "# Corrections will only happen if correct-player-movement is set to true.",
                "",
                "player-movement-score-threshold=20",
                "# The number of incongruent time intervals needed before abnormal behavior is reported.",
                "# Disabled by server-authoritative-movement.",
                "",
                "player-movement-distance-threshold=0.3",
                "# The difference between server and client positions that needs to be exceeded before abnormal behavior is detected.",
                "# Disabled by server-authoritative-movement.",
                "",
                "player-movement-duration-threshold-in-ms=500",
                "# The duration of time the server and client positions can be out of sync (as defined by player-movement-distance-threshold)",
                "# before the abnormal movement score is incremented. This value is defined in milliseconds.",
                "# Disabled by server-authoritative-movement.",
                "",
                "correct-player-movement=false"
            ]

            with open(self.server_properties, 'w', encoding='utf-8') as f:
                f.write('\n'.join(default_properties))

            self.add_message(f"已创建默认server.properties，种子: {seed}")
            return True
        except Exception as e:
            self.add_message(f"创建server.properties失败: {e}", "error")
            return False

    def check_log_file(self):
        """检查日志文件是否包含目标物品"""
        try:
            if not os.path.exists(self.world_db_path):
                return False, None

            log_files = []
            for file in os.listdir(self.world_db_path):
                if file.endswith('.log') or file.endswith('.ldb'):
                    file_path = os.path.join(self.world_db_path, file)
                    log_files.append((file_path, os.path.getmtime(file_path)))

            if not log_files:
                return False, None

            log_files.sort(key=lambda x: x[1], reverse=True)
            latest_log = log_files[0][0]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_file = os.path.join(self.mclog_dir, f"log_{timestamp}.txt")

            shutil.copy2(latest_log, target_file)

            try:
                with open(target_file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='ignore')

                if self.target_item in content:
                    self.last_log_file = target_file
                    return True, target_file
                else:
                    if os.path.exists(target_file):
                        os.remove(target_file)
                    return False, None

            except Exception as e:
                self.add_message(f"读取日志文件失败: {e}", "error")
                if os.path.exists(target_file):
                    os.remove(target_file)
                return False, None

        except Exception as e:
            self.add_message(f"检查日志文件时出错: {e}", "error")
            return False, None

    def clear_mclog_directory(self):
        """清空mclog目录中的所有文件"""
        try:
            if os.path.exists(self.mclog_dir):
                for filename in os.listdir(self.mclog_dir):
                    file_path = os.path.join(self.mclog_dir, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        self.add_message(f"删除{file_path}时出错: {e}", "warning")
                return True
        except Exception as e:
            self.add_message(f"清空mclog目录时出错: {e}", "error")
        return False

    def start_log_monitor(self):
        """启动日志监控线程"""
        if self.is_monitoring:
            return

        self.is_monitoring = True

        def monitor_loop():
            self.add_message(f"监控线程启动，检查间隔: {self.monitor_interval}秒")

            while self.is_monitoring and self.current_session:
                try:
                    detected, log_file = self.check_log_file()

                    if detected:
                        self.add_message("检测到目标物品，开始结算流程")
                        self.is_monitoring = False

                        if self.current_session:
                            self.load_scores()

                            raw_elapsed_seconds = time.time() - self.current_session['start_time']
                            raw_minutes = raw_elapsed_seconds / 60

                            seed = self.current_session.get('seed', '未知')
                            village_type = self.current_session.get('village_type', '未知')
                            increased_drop_rate = self.current_session.get('increased_drop_rate', False)
                            pure_trial_bonus = self.current_session.get('pure_trial_bonus', 0)

                            effective_seconds = max(0, raw_elapsed_seconds - 30)
                            effective_minutes = effective_seconds / 60

                            base_score = 4

                            old_total_score = self.scores_data.get('total_score', 0)
                            old_rank_info = self.get_rank_info(old_total_score)

                            time_score = self.calculate_time_bonus(effective_minutes, old_rank_info['type'])
                            village_score = self.get_village_bonus(village_type, old_rank_info['type'])
                            pure_trial_score = pure_trial_bonus if not increased_drop_rate else 0

                            total_score = base_score + time_score + village_score + pure_trial_score

                            self.scores_data['total_attempts'] = self.scores_data.get('total_attempts', 0) + 1
                            self.scores_data['successful_attempts'] = self.scores_data.get('successful_attempts', 0) + 1

                            score_record = {
                                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'seed': seed,
                                'village_type': village_type,
                                'raw_time_seconds': raw_elapsed_seconds,
                                'effective_time_seconds': effective_seconds,
                                'effective_minutes': effective_minutes,
                                'total_score': total_score,
                                'base_score': base_score,
                                'time_score': time_score,
                                'village_score': village_score,
                                'pure_trial_score': pure_trial_score,
                                'old_rank_type': old_rank_info['type'],
                                'increased_drop_rate': increased_drop_rate,
                                'success': True
                            }

                            if 'scores' not in self.scores_data:
                                self.scores_data['scores'] = []
                            self.scores_data['scores'].append(score_record)

                            current_best_time = self.scores_data.get('best_time')
                            if current_best_time is None or effective_seconds < current_best_time:
                                self.scores_data['best_time'] = effective_seconds
                                self.scores_data['best_seed'] = seed
                                self.scores_data['best_village_type'] = village_type

                            new_total_score = old_total_score + total_score
                            self.scores_data['total_score'] = new_total_score

                            new_rank_info = self.get_rank_info(new_total_score)

                            self.scores_data['current_rank'] = new_rank_info['name']
                            self.scores_data['rank_progress'] = new_rank_info['progress_percent']
                            if new_rank_info['is_netherite']:
                                self.scores_data['rank_stars'] = new_rank_info['stars']

                            self.save_scores()

                            time_display = self.format_time_display(effective_seconds)
                            raw_time_display = self.format_time_display(raw_elapsed_seconds)

                            drop_rate_status = "增加掉率" if increased_drop_rate else "正常掉率"

                            result_msg = f"""FSG挑战完成！🎉
种子: {seed}
村庄类型: {village_type}
掉率设置: {drop_rate_status}

用时详情:
原始用时: {raw_time_display} (扣除30秒加载时间后)
有效用时: {time_display}

得分详情:
基础分: +{base_score}分
时间加分 ({effective_minutes:.1f}分钟): +{time_score}分
村庄加分: +{village_score}分
{"纯粹试炼: +" + str(pure_trial_score) + "分" if pure_trial_score > 0 else ""}
本次得分: {total_score}分

当前段位:
{self.format_rank_display(new_total_score)}
{self.get_rank_progress_bar(new_rank_info['progress_percent'])} ({int(new_rank_info['progress_percent'])}%)

服务器将在60秒后关闭..."""

                            self.add_message(result_msg)

                            self.start_shutdown_timer(60)
                            return

                    time.sleep(self.monitor_interval)

                except Exception as e:
                    self.add_message(f"监控循环出错: {e}", "error")
                    time.sleep(self.monitor_interval)

            self.add_message("监控线程结束")
            self.is_monitoring = False

        self.log_monitor = threading.Thread(target=monitor_loop)
        self.log_monitor.daemon = True
        self.log_monitor.start()
        self.add_message("监控线程已启动")

    def calculate_time_bonus(self, effective_minutes, rank_type):
        """根据段位类型和时间计算时间加分"""
        if rank_type in ["wood", "stone"]:
            rules = self.time_bonus_rules["wood_stone"]
            if effective_minutes <= 12:
                return rules["12"]
            elif effective_minutes <= 15:
                return rules["15"]
            elif effective_minutes <= 18:
                return rules["18"]
            elif effective_minutes <= 20:
                return rules["20"]
            elif effective_minutes <= 25:
                return rules["25"]
            elif effective_minutes <= 30:
                return rules["30"]
            else:
                return 0

        elif rank_type in ["copper", "iron"]:
            rules = self.time_bonus_rules["copper_iron"]
            if effective_minutes <= 12:
                return rules["12"]
            elif effective_minutes <= 14:
                return rules["14"]
            elif effective_minutes <= 16:
                return rules["16"]
            elif effective_minutes <= 18:
                return rules["18"]
            elif effective_minutes <= 20:
                return rules["20"]
            elif effective_minutes <= 25:
                return rules["25"]
            else:
                return 0

        else:
            rules = self.time_bonus_rules["gold_diamond_netherite"]
            if effective_minutes <= 7:
                return rules["7"]
            elif effective_minutes <= 8:
                return rules["8"]
            elif effective_minutes <= 10:
                return rules["10"]
            elif effective_minutes <= 12:
                return rules["12"]
            elif effective_minutes <= 15:
                return rules["15"]
            elif effective_minutes <= 20:
                return rules["20"]
            else:
                return 0

    def get_rank_info(self, total_score):
        """根据总分获取详细的段位信息"""
        total_score = max(0, total_score)

        current_rank = None
        for rank in self.ranks:
            if total_score >= rank["min_score"]:
                current_rank = rank
            else:
                break

        if not current_rank:
            current_rank = self.ranks[-1]

        rank_start_score = current_rank["min_score"]
        score_in_rank = total_score - rank_start_score
        interval = current_rank["interval"]

        if current_rank["name"] == "下界合金":
            stars = (total_score - 480) // 30 + 1
            progress_percent = (score_in_rank % 30) / 30 * 100
            return {
                "name": current_rank["name"],
                "type": current_rank["type"],
                "symbol": self.rank_symbols[current_rank["type"]],
                "min_score": rank_start_score,
                "score_in_rank": score_in_rank,
                "progress_percent": progress_percent,
                "stars": stars,
                "interval": interval,
                "total_score": total_score,
                "is_netherite": True
            }
        else:
            progress_percent = (score_in_rank % interval) / interval * 100
            return {
                "name": current_rank["name"],
                "type": current_rank["type"],
                "symbol": self.rank_symbols[current_rank["type"]],
                "min_score": rank_start_score,
                "score_in_rank": score_in_rank,
                "progress_percent": progress_percent,
                "stars": 0,
                "interval": interval,
                "total_score": total_score,
                "is_netherite": False
            }

    def format_rank_display(self, total_score):
        """格式化段位显示"""
        rank_info = self.get_rank_info(total_score)

        if rank_info["is_netherite"]:
            progress_text = f"{int(rank_info['progress_percent'])}%"
            return f"{rank_info['symbol']} {rank_info['name']} {rank_info['stars']} ★({progress_text})"
        else:
            progress_text = f"{int(rank_info['progress_percent'])}%"
            return f"{rank_info['symbol']} {rank_info['name']}({progress_text})"

    def get_rank_progress_bar(self, progress_percent):
        """获取段位进度条"""
        total_blocks = 20
        filled_blocks = int(progress_percent / 100 * total_blocks)
        empty_blocks = total_blocks - filled_blocks

        filled_char = "█"
        empty_char = "░"

        return filled_char * filled_blocks + empty_char * empty_blocks

    def start_shutdown_timer(self, seconds):
        """启动60秒关闭计时器"""
        self.add_message(f"启动{seconds}秒关闭计时器")
        self.is_shutting_down = True

        if self.shutdown_timer:
            self.shutdown_timer.cancel()

        self.shutdown_timer = threading.Timer(seconds, self.force_shutdown)
        self.shutdown_timer.daemon = True
        self.shutdown_timer.start()

        self.start_shutdown_countdown(seconds)

    def start_shutdown_countdown(self, total_seconds):
        """显示倒计时"""

        def countdown():
            remaining = total_seconds
            while remaining > 0 and self.is_shutting_down:
                if remaining <= 5 or remaining % 10 == 0:
                    self.add_message(f"服务器将在 {remaining} 秒后关闭...")
                time.sleep(1)
                remaining -= 1

        threading.Thread(target=countdown, daemon=True).start()

    def cancel_shutdown_timer(self):
        """取消关闭计时器"""
        if self.shutdown_timer:
            self.add_message("取消关闭计时器")
            self.shutdown_timer.cancel()
            self.shutdown_timer = None
        self.is_shutting_down = False

    def force_shutdown(self):
        """强制关闭服务器和清理"""
        self.add_message("开始关闭服务器...")

        self.is_monitoring = False
        self.cancel_shutdown_timer()

        self.stop_server()

        if self.current_session:
            self.current_session['waiting_shutdown'] = True

        self.add_message("服务器已关闭，FSG模式结束")
        self.add_message("现在可以开始新的挑战")

        self.current_session = None

    def start_server(self):
        """启动服务器"""
        try:
            if not os.path.exists(self.bedrock_server_exe):
                self.add_message(f"找不到bedrock_server.exe！请检查路径: {self.bedrock_server_exe}", "error")
                return False

            self.add_message(f"正在启动服务器: {self.bedrock_server_exe}")
            self.server_process = subprocess.Popen(
                [self.bedrock_server_exe],
                cwd=self.server_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            self.add_message("服务器启动中，请稍候...")

            time.sleep(3)

            if self.server_process.poll() is not None:
                stdout, stderr = self.server_process.communicate()
                error_msg = stderr if stderr else "服务器进程异常退出"
                self.add_message(f"服务器启动失败: {error_msg}", "error")
                return False

            self.add_message("服务器启动成功！")
            return True

        except Exception as e:
            self.add_message(f"服务器启动失败: {e}", "error")
            return False

    def start_fsg(self, increased_drop_rate=False):
        """开始新的FSG挑战"""
        if self.current_session:
            if self.current_session.get('waiting_shutdown', False):
                self.current_session = None
                self.add_message("清理完成，现在可以开始新的FSG挑战")
                return True
            elif self.current_session.get('completed', False):
                self.add_message("上一个FSG已完成，服务器将在60秒后关闭")
                self.add_message("如果想立即开始新的挑战，请先取消当前FSG")
                return False
            else:
                self.add_message("已经有一个FSG在进行中了！")
                return False

        # 设置掉率参数
        self.increased_drop_rate = increased_drop_rate
        self.pure_trial_bonus = 0 if increased_drop_rate else 2

        self.add_message("正在准备FSG挑战...")

        # 在新线程中启动FSG
        threading.Thread(target=self._continue_fsg_start, daemon=True).start()
        return True

    def _continue_fsg_start(self):
        """继续FSG启动流程"""
        self.clear_mclog_directory()

        seed, village_type = self.generate_seed()

        self.add_message(f"生成种子: {seed}")
        self.add_message(f"村庄类型: {village_type}")
        self.add_message(
            f"掉率设置: {'增加' if self.increased_drop_rate else '正常'} (纯粹试炼: +{self.pure_trial_bonus}分)")
        self.add_message("正在准备服务器...")

        # 1. 强制关闭现有服务器
        self.add_message("步骤1: 停止现有服务器")
        self.stop_server()
        self.cancel_shutdown_timer()

        # 2. 修改服务器种子
        self.add_message(f"步骤2: 修改服务器种子为 {seed}")
        if not self.update_seed_in_properties(seed):
            self.add_message("修改服务器配置失败！", "error")
            return

        # 3. 清理世界文件
        self.add_message("步骤3: 清理世界文件")
        self.clear_world_files()

        # 4. 复制FSG资源文件
        self.add_message("步骤4: 复制FSG资源文件")
        if not self.copy_fsg_resources():
            self.add_message("复制资源文件失败！", "error")
            return

        # 5. 创建新会话
        time.sleep(3)
        self.current_session = {
            'seed': seed,
            'start_time': time.time(),
            'elapsed_seconds': 0,
            'completed': False,
            'waiting_shutdown': False,
            'village_type': village_type,
            'increased_drop_rate': self.increased_drop_rate,
            'pure_trial_bonus': self.pure_trial_bonus
        }

        # 6. 启动服务器
        time.sleep(3)
        self.add_message("步骤5: 启动服务器")

        if not self.start_server():
            self.current_session = None
            return

        self.add_message("计时已启动。")
        self.add_message("服务器已启动成功")

        # 启动日志监控
        self.start_log_monitor()

        self.add_message("自动检测已启动，正在监控游戏进度...请立刻开始游戏！")

    def get_status(self):
        """获取FSG状态"""
        if not self.current_session:
            return {
                "active": False,
                "message": "没有正在进行的FSG挑战"
            }

        elapsed = time.time() - self.current_session['start_time']
        minutes = elapsed / 60

        current_score = self.scores_data.get('total_score', 0)
        rank_info = self.get_rank_info(current_score)

        status = {
            "active": True,
            "seed": self.current_session['seed'],
            "village_type": self.current_session['village_type'],
            "elapsed_minutes": round(minutes, 1),
            "elapsed_seconds": int(elapsed),
            "current_rank": self.format_rank_display(current_score),
            "rank_progress": rank_info['progress_percent'],
            "monitoring": self.is_monitoring,
            "increased_drop_rate": self.current_session.get('increased_drop_rate', False),
            "pure_trial_bonus": self.current_session.get('pure_trial_bonus', 0)
        }

        if self.current_session.get('completed', False):
            if self.is_shutting_down:
                status["state"] = "挑战完成，等待服务器关闭..."
            else:
                status["state"] = "挑战完成"
        else:
            status["state"] = "进行中"

        if self.is_shutting_down:
            status["shutdown_countdown"] = True

        return status

    def cancel_fsg(self, confirmed=False):
        """取消当前FSG"""
        if not self.current_session:
            self.add_message("没有正在进行的FSG挑战")
            return False

        if self.current_session.get('waiting_shutdown', False):
            self.current_session = None
            self.add_message("已清理完成")
            return True

        if self.current_session.get('completed', False):
            self.add_message("正在提前关闭服务器...")
            self.cancel_shutdown_timer()
            self.force_shutdown()
            return True

        current_score = self.scores_data.get('total_score', 0)
        rank_info = self.get_rank_info(current_score)

        # 金以上段位需要确认
        if rank_info['type'] in ["gold", "diamond", "netherite"] and not confirmed:
            # 这里应该返回需要确认的信息，由Web界面处理
            return "need_confirmation"

        # 执行取消
        is_gold_plus = rank_info['type'] in ["gold", "diamond", "netherite"]
        self._fail_fsg_challenge(rank_info, is_gold_plus)
        return True

    def _fail_fsg_challenge(self, rank_info, is_gold_plus=True):
        """处理FSG失败结算"""
        try:
            self.load_scores()

            seed = self.current_session.get('seed', '未知')
            village_type = self.current_session.get('village_type', '未知')
            increased_drop_rate = self.current_session.get('increased_drop_rate', False)
            pure_trial_bonus = self.current_session.get('pure_trial_bonus', 0)

            old_total_score = self.scores_data.get('total_score', 0)
            old_rank_info = self.get_rank_info(old_total_score)

            if is_gold_plus:
                penalty_score = -4
                village_score = self.get_village_bonus(village_type, old_rank_info['type'])
                pure_trial_score = pure_trial_bonus if not increased_drop_rate else 0
                total_score = penalty_score + village_score + pure_trial_score
            else:
                penalty_score = 0
                village_score = 0
                pure_trial_score = 0
                total_score = 0

            self.scores_data['total_attempts'] = self.scores_data.get('total_attempts', 0) + 1

            fail_record = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'seed': seed,
                'village_type': village_type,
                'total_score': total_score,
                'penalty_score': penalty_score,
                'village_score': village_score,
                'pure_trial_score': pure_trial_score,
                'old_rank_type': old_rank_info['type'],
                'increased_drop_rate': increased_drop_rate,
                'success': False,
                'is_gold_plus': is_gold_plus
            }

            if 'scores' not in self.scores_data:
                self.scores_data['scores'] = []
            self.scores_data['scores'].append(fail_record)

            new_total_score = old_total_score + total_score
            self.scores_data['total_score'] = new_total_score

            new_rank_info = self.get_rank_info(new_total_score)

            self.scores_data['current_rank'] = new_rank_info['name']
            self.scores_data['rank_progress'] = new_rank_info['progress_percent']
            if new_rank_info['is_netherite']:
                self.scores_data['rank_stars'] = new_rank_info['stars']

            self.save_scores()

            drop_rate_status = "增加掉率" if increased_drop_rate else "正常掉率"

            fail_msg = f"""FSG挑战失败
种子: {seed}
村庄类型: {village_type}
掉率设置: {drop_rate_status}
段位等级: {'金以上' if is_gold_plus else '金以下'}

得分详情:
{"失败: " + str(penalty_score) + "分" if penalty_score != 0 else "失败保护: 0分"}
村庄分: +{village_score}分
{"纯粹试炼: +" + str(pure_trial_score) + "分" if pure_trial_score > 0 else ""}
总计: {total_score}分

当前段位:
{self.format_rank_display(new_total_score)}
{self.get_rank_progress_bar(new_rank_info['progress_percent'])} ({int(new_rank_info['progress_percent'])}%)"""

            self.add_message(fail_msg)

            self.is_monitoring = False
            self.stop_server()
            self.cancel_shutdown_timer()
            self.current_session = None

        except Exception as e:
            self.add_message(f"失败结算出错: {e}", "error")

    def show_scores(self):
        """获取成绩排行榜"""
        with self.lock:
            self.load_scores()

            total_score = self.scores_data.get('total_score', 0)
            rank_info = self.get_rank_info(total_score)

            progress_bar = self.get_rank_progress_bar(rank_info['progress_percent'])

            # 最近成绩
            recent_scores = []
            scores_list = self.scores_data.get('scores', [])
            valid_scores = [s for s in scores_list if isinstance(s, dict)]

            if valid_scores:
                recent_scores = valid_scores[-5:][::-1]

            # 最佳成绩
            best_scores = []
            top_scores = self.scores_data.get('top_scores', [])
            valid_top_scores = [s for s in top_scores if isinstance(s, dict)]

            if valid_top_scores:
                best_scores = valid_top_scores[:3]

            total_attempts = self.scores_data.get('total_attempts', 0)
            successful_attempts = self.scores_data.get('successful_attempts', 0)
            success_rate = (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0

            return {
                "total_score": total_score,
                "current_rank": self.format_rank_display(total_score),
                "rank_progress": rank_info['progress_percent'],
                "progress_bar": progress_bar,
                "total_attempts": total_attempts,
                "successful_attempts": successful_attempts,
                "success_rate": round(success_rate, 1),
                "best_time": self.scores_data.get('best_time'),
                "best_seed": self.scores_data.get('best_seed'),
                "best_village_type": self.scores_data.get('best_village_type'),
                "recent_scores": recent_scores,
                "best_scores": best_scores
            }


# 创建Flask Web应用
app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 全局FSG实例
fsg_system = None


def get_fsg_system():
    """获取FSG系统实例（单例模式）"""
    global fsg_system
    if fsg_system is None:
        fsg_system = FSGSystem()
    return fsg_system


# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FSG手机控制端</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 600px;
            margin: 0 auto;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }

        .card {
            background: white;
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }

        .status-card {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }

        .button-group {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 20px;
        }

        .drop-rate-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 20px;
        }

        .button {
            padding: 16px 20px;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
        }

        .button-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .button-success {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
        }

        .button-danger {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }

        .button-secondary {
            background: #f0f0f0;
            color: #333;
        }

        .button:active {
            transform: translateY(2px);
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .status-item {
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.2);
        }

        .status-label {
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 5px;
        }

        .status-value {
            font-size: 18px;
            font-weight: 600;
        }

        .messages-container {
            max-height: 300px;
            overflow-y: auto;
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            margin-top: 20px;
        }

        .message {
            padding: 8px 12px;
            margin-bottom: 8px;
            border-radius: 8px;
            background: white;
            border-left: 4px solid #667eea;
            font-size: 14px;
        }

        .message-time {
            font-size: 12px;
            color: #666;
            margin-right: 10px;
        }

        .message-error {
            border-left-color: #f5576c;
            background: #fff5f5;
        }

        .message-success {
            border-left-color: #4facfe;
            background: #f0f9ff;
        }

        .progress-bar {
            height: 20px;
            background: rgba(255,255,255,0.2);
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
            border-radius: 10px;
            transition: width 0.3s ease;
        }

        .rank-display {
            font-size: 24px;
            text-align: center;
            margin: 20px 0;
            font-weight: bold;
        }

        @media (max-width: 480px) {
            .button-group {
                grid-template-columns: 1fr;
            }

            .drop-rate-buttons {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎮 FSG手机控制端</h1>
            <p>远程控制Minecraft FSG挑战</p>
        </div>

        <div class="card status-card" id="statusCard">
            <div class="status-item">
                <div class="status-label">当前状态</div>
                <div class="status-value" id="currentStatus">等待连接...</div>
            </div>

            <div id="activeSessionInfo" style="display: none;">
                <div class="status-item">
                    <div class="status-label">种子</div>
                    <div class="status-value" id="currentSeed">-</div>
                </div>

                <div class="status-item">
                    <div class="status-label">村庄类型</div>
                    <div class="status-value" id="villageType">-</div>
                </div>

                <div class="status-item">
                    <div class="status-label">用时</div>
                    <div class="status-value" id="elapsedTime">00:00</div>
                </div>

                <div class="status-item">
                    <div class="status-label">掉率设置</div>
                    <div class="status-value" id="dropRateSetting">正常</div>
                </div>
            </div>

            <div class="status-item">
                <div class="status-label">当前段位</div>
                <div class="rank-display" id="currentRank">🪵 木头III(0%)</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="rankProgress" style="width: 0%"></div>
                </div>
                <div style="text-align: center; font-size: 14px;" id="rankScore">总积分: 0分</div>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-bottom: 20px; color: #333;">控制面板</h3>

            <div class="drop-rate-buttons" id="dropRateButtons" style="display: none;">
                <button class="button button-primary" onclick="startFSG(false)">
                    🎯 正常掉率 (+2纯粹分)
                </button>
                <button class="button button-success" onclick="startFSG(true)">
                    ⚡ 增加掉率 (无额外分)
                </button>
            </div>

            <div class="button-group" id="mainButtons">
                <button class="button button-primary" onclick="showDropRateButtons()" id="startButton">
                    🚀 开始新挑战
                </button>
                <button class="button button-danger" onclick="cancelFSG()" id="cancelButton" disabled>
                    ⏹️ 取消挑战
                </button>
                <button class="button button-secondary" onclick="getScores()">
                    📊 查看排行榜
                </button>
                <button class="button button-secondary" onclick="refreshStatus()">
                    🔄 刷新状态
                </button>
            </div>

            <div id="confirmationDialog" style="display: none; margin-top: 20px; padding: 15px; background: #fff5f5; border-radius: 10px;">
                <p style="margin-bottom: 15px; color: #d32f2f; font-weight: 600;">
                    ⚠️ 金以上段位退出将扣除4分！
                </p>
                <p style="margin-bottom: 15px;">确认要退出FSG挑战吗？</p>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <button class="button button-danger" onclick="confirmCancel(true)">
                        确认取消
                    </button>
                    <button class="button button-secondary" onclick="hideConfirmation()">
                        继续挑战
                    </button>
                </div>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-bottom: 15px; color: #333;">系统消息</h3>
            <div class="messages-container" id="messagesContainer">
                <div class="message">
                    <span class="message-time">连接中...</span>
                    等待接收消息
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentSession = null;
        let refreshInterval = null;

        // 页面加载时初始化
        document.addEventListener('DOMContentLoaded', function() {
            refreshStatus();
            refreshMessages();
            startAutoRefresh();
        });

        // 自动刷新状态和消息
        function startAutoRefresh() {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(() => {
                refreshStatus();
                refreshMessages();
            }, 3000); // 每3秒刷新一次
        }

        // 刷新状态
        async function refreshStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();

                updateStatusDisplay(data);

            } catch (error) {
                console.error('刷新状态失败:', error);
                document.getElementById('currentStatus').textContent = '连接失败';
            }
        }

        // 更新状态显示
        function updateStatusDisplay(data) {
            const statusElement = document.getElementById('currentStatus');
            const activeSessionInfo = document.getElementById('activeSessionInfo');
            const cancelButton = document.getElementById('cancelButton');

            if (data.active) {
                statusElement.textContent = data.state || '进行中';
                activeSessionInfo.style.display = 'block';

                // 更新会话信息
                document.getElementById('currentSeed').textContent = data.seed;
                document.getElementById('villageType').textContent = data.village_type;
                document.getElementById('elapsedTime').textContent = 
                    `${Math.floor(data.elapsed_seconds / 60).toString().padStart(2, '0')}:${(data.elapsed_seconds % 60).toString().padStart(2, '0')}`;
                document.getElementById('dropRateSetting').textContent = 
                    data.increased_drop_rate ? '增加掉率' : '正常掉率';

                // 禁用开始按钮，启用取消按钮
                document.getElementById('startButton').disabled = true;
                cancelButton.disabled = false;
                document.getElementById('dropRateButtons').style.display = 'none';

                currentSession = data;

            } else {
                statusElement.textContent = data.message || '空闲';
                activeSessionInfo.style.display = 'none';

                // 启用开始按钮，禁用取消按钮
                document.getElementById('startButton').disabled = false;
                cancelButton.disabled = true;

                currentSession = null;
            }

            // 更新段位显示
            if (data.rank_info) {
                document.getElementById('currentRank').textContent = data.rank_info.current_rank;
                document.getElementById('rankProgress').style.width = data.rank_info.rank_progress + '%';
                document.getElementById('rankScore').textContent = `总积分: ${data.rank_info.total_score}分`;
            }
        }

        // 刷新消息
        async function refreshMessages() {
            try {
                const response = await fetch('/api/messages');
                const messages = await response.json();

                const container = document.getElementById('messagesContainer');
                container.innerHTML = '';

                if (messages.length === 0) {
                    container.innerHTML = '<div class="message">暂无消息</div>';
                    return;
                }

                messages.forEach(msg => {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message';

                    if (msg.type === 'error') {
                        messageDiv.classList.add('message-error');
                    } else if (msg.type === 'success') {
                        messageDiv.classList.add('message-success');
                    }

                    messageDiv.innerHTML = `
                        <span class="message-time">${msg.time}</span>
                        ${msg.message}
                    `;

                    container.appendChild(messageDiv);
                });

                // 滚动到底部
                container.scrollTop = container.scrollHeight;

            } catch (error) {
                console.error('刷新消息失败:', error);
            }
        }

        // 显示掉率选择按钮
        function showDropRateButtons() {
            if (currentSession) {
                alert('当前已有进行中的挑战，请先取消或完成当前挑战');
                return;
            }

            document.getElementById('dropRateButtons').style.display = 'grid';
            document.getElementById('mainButtons').style.display = 'none';
        }

        // 开始FSG挑战
        async function startFSG(increasedDropRate) {
            try {
                const response = await fetch('/api/start', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        increased_drop_rate: increasedDropRate
                    })
                });

                const data = await response.json();

                if (data.success) {
                    alert('FSG挑战已启动！请查看消息面板获取详情。');
                } else {
                    alert('启动失败: ' + (data.message || '未知错误'));
                }

                // 恢复按钮显示
                document.getElementById('dropRateButtons').style.display = 'none';
                document.getElementById('mainButtons').style.display = 'grid';

                // 刷新状态
                refreshStatus();
                refreshMessages();

            } catch (error) {
                console.error('启动失败:', error);
                alert('启动失败，请检查网络连接');

                document.getElementById('dropRateButtons').style.display = 'none';
                document.getElementById('mainButtons').style.display = 'grid';
            }
        }

        // 取消FSG挑战
        async function cancelFSG() {
            if (!currentSession) {
                alert('当前没有进行中的挑战');
                return;
            }

            try {
                // 先检查是否需要确认
                const checkResponse = await fetch('/api/cancel', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        confirmed: false
                    })
                });

                const checkData = await checkResponse.json();

                if (checkData.need_confirmation) {
                    // 显示确认对话框
                    document.getElementById('confirmationDialog').style.display = 'block';
                } else {
                    // 直接取消
                    await confirmCancel(false);
                }

            } catch (error) {
                console.error('取消失败:', error);
                alert('取消失败，请重试');
            }
        }

        // 确认取消
        async function confirmCancel(needsConfirm) {
            try {
                const response = await fetch('/api/cancel', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        confirmed: needsConfirm
                    })
                });

                const data = await response.json();

                if (data.success) {
                    alert('FSG挑战已取消');
                } else {
                    alert('取消失败: ' + (data.message || '未知错误'));
                }

                // 隐藏确认对话框
                hideConfirmation();

                // 刷新状态和消息
                refreshStatus();
                refreshMessages();

            } catch (error) {
                console.error('确认取消失败:', error);
                alert('操作失败，请重试');
            }
        }

        // 隐藏确认对话框
        function hideConfirmation() {
            document.getElementById('confirmationDialog').style.display = 'none';
        }

        // 获取排行榜
        async function getScores() {
            try {
                const response = await fetch('/api/scores');
                const data = await response.json();

                // 显示排行榜信息
                let scoresHtml = `
                    <h3 style="margin-bottom: 15px; color: #333;">FSG排行榜</h3>
                    <div style="margin-bottom: 15px;">
                        <div style="font-size: 20px; font-weight: bold; text-align: center; margin-bottom: 10px;">
                            ${data.current_rank}
                        </div>
                        <div style="text-align: center; margin-bottom: 15px;">
                            总积分: ${data.total_score}分<br>
                            挑战次数: ${data.total_attempts}次<br>
                            成功率: ${data.success_rate}%
                        </div>
                    </div>
                `;

                if (data.best_scores && data.best_scores.length > 0) {
                    scoresHtml += `<h4 style="margin-bottom: 10px;">最佳成绩</h4>`;
                    data.best_scores.forEach((score, index) => {
                        const minutes = Math.floor(score.effective_time_seconds / 60);
                        const seconds = Math.floor(score.effective_time_seconds % 60);
                        scoresHtml += `
                            <div style="margin-bottom: 8px; padding: 8px; background: #f0f9ff; border-radius: 6px;">
                                ${index + 1}. ${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')} - 
                                ${score.total_score}分 (${score.old_rank_type})
                            </div>
                        `;
                    });
                }

                alert(scoresHtml);

            } catch (error) {
                console.error('获取排行榜失败:', error);
                alert('获取排行榜失败，请重试');
            }
        }
    </script>
</body>
</html>
'''


# API路由
@app.route('/')
def index():
    """主页面"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/status', methods=['GET'])
def api_status():
    """获取当前状态"""
    system = get_fsg_system()
    status = system.get_status()

    # 添加段位信息
    current_score = system.scores_data.get('total_score', 0)
    rank_info = system.get_rank_info(current_score)

    status['rank_info'] = {
        'current_rank': system.format_rank_display(current_score),
        'rank_progress': rank_info['progress_percent'],
        'total_score': current_score
    }

    return jsonify(status)


@app.route('/api/start', methods=['POST'])
def api_start():
    """开始新的FSG挑战"""
    system = get_fsg_system()

    data = request.get_json()
    increased_drop_rate = data.get('increased_drop_rate', False) if data else False

    success = system.start_fsg(increased_drop_rate)

    return jsonify({
        'success': success,
        'message': 'FSG挑战已启动' if success else '启动失败'
    })


@app.route('/api/cancel', methods=['POST'])
def api_cancel():
    """取消当前FSG挑战"""
    system = get_fsg_system()

    data = request.get_json()
    confirmed = data.get('confirmed', False) if data else False

    result = system.cancel_fsg(confirmed)

    if result == "need_confirmation":
        return jsonify({
            'success': False,
            'need_confirmation': True,
            'message': '金以上段位需要确认取消'
        })

    return jsonify({
        'success': result,
        'message': 'FSG挑战已取消' if result else '取消失败'
    })


@app.route('/api/scores', methods=['GET'])
def api_scores():
    """获取排行榜"""
    system = get_fsg_system()
    scores = system.show_scores()
    return jsonify(scores)


@app.route('/api/messages', methods=['GET'])
def api_messages():
    """获取最近消息"""
    system = get_fsg_system()
    messages = system.get_messages(20)
    return jsonify(messages)


@app.route('/api/health', methods=['GET'])
def api_health():
    """健康检查"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    # 初始化FSG系统
    fsg_system = FSGSystem()

    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)