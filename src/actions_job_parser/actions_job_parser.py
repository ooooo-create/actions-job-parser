import argparse
from pathlib import Path

import yaml


def find_workflow_files(repo_root: Path):
    """
    查找并返回仓库中 '.github/workflows' 目录下的所有 YAML 工作流文件。

    Args:
        repo_root (Path): 仓库的根目录路径。

    Returns:
        list: 包含所有工作流文件 Path 对象的列表。
    """
    workflows_path = repo_root / ".github" / "workflows"
    if not workflows_path.is_dir():
        print(f"警告: 目录不存在 {workflows_path}")
        return []
    # 同时查找 .yml 和 .yaml 后缀的文件
    return list(workflows_path.glob("*.yml")) + list(workflows_path.glob("*.yaml"))


def is_reusable_workflow(file_path: Path):
    """
    检查一个工作流文件是否是可复用的（即包含 'on: workflow_call' 触发器）。

    Args:
        file_path (Path): 要检查的工作流文件的路径。

    Returns:
        bool: 如果是可复用工作流则返回 True，否则返回 False。
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            # 必须有 'on' 字段
            if not workflow or "on" not in workflow:
                return False
            on_trigger = workflow["on"]
            # 'on' 字段是一个字典，并且只包含 'workflow_call' 键
            if isinstance(on_trigger, dict) and "workflow_call" in on_trigger and len(on_trigger) == 1:
                return True
    except (yaml.YAMLError, OSError) as e:
        print(f"错误: 读取或解析文件时出错 {file_path}: {e}")
    return False


def parse_workflow_jobs(file_path: Path, repo_root: Path, all_workflows: list[Path]):
    """
    解析单个工作流文件，提取所有 job 名称。
    此函数会递归处理本地的可复用工作流（reusable workflows）。

    Args:
        file_path (Path): 要解析的工作流文件的路径。
        repo_root (Path): 仓库的根目录路径。
        all_workflows (list): 包含所有找到的工作流文件的列表，用于查找被调用的工作流。

    Returns:
        list: 从该工作流中解析出的所有 job 名称的列表。
    """
    job_names = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            if not workflow or "jobs" not in workflow:
                return []

            for job_id, job_details in workflow.get("jobs", {}).items():
                # job 的显示名称，如果未定义 'name'，则使用其 ID
                job_name = job_details.get("name", job_id)

                # 检查 job 是否调用了另一个工作流
                if "uses" in job_details:
                    uses_path = job_details["uses"]
                    if uses_path.startswith("./.github/workflows/"):
                        reusable_workflow_path = Path(repo_root) / uses_path[2:]

                        # 从所有工作流文件列表中找到被调用者的完整路径
                        callee_path = None
                        for wf in all_workflows:
                            if wf.name == reusable_workflow_path.name:
                                callee_path = wf
                                break

                        if callee_path and callee_path.exists():
                            # 获取调用方 job 的名称作为前缀
                            caller_job_name = job_details.get("name", job_id)
                            # 递归解析被调用的工作流
                            sub_jobs = parse_workflow_jobs(callee_path, repo_root, all_workflows)
                            # 将调用者和被调用者的 job 名称组合起来
                            for sub_job_name in sub_jobs:
                                job_names.append(f"{caller_job_name} / {sub_job_name}")
                        else:
                            # 如果找不到被调用的工作流文件，则只使用当前 job 的名称
                            print(f"警告: 找不到可复用工作流 {uses_path}")
                            job_names.append(job_name)
                    else:
                        # 对于远程工作流（如 'actions/checkout@v4'），我们无法解析其内部，
                        # 因此直接使用当前 job 的名称。
                        job_names.append(job_name)
                else:
                    # 这是一个常规的、独立的 job
                    job_names.append(job_name)
    except yaml.YAMLError as e:
        print(f"错误: 解析 YAML 文件时出错 {file_path}: {e}")
    except Exception as e:
        print(f"错误: 处理文件时发生未知错误 {file_path}: {e}")

    return job_names


def main():
    """
    主函数，负责执行整个解析流程。
    1. 解析命令行参数。
    2. 查找所有工作流文件。
    3. 筛选出顶层工作流（非可复用工作流）。
    4. 遍历并解析每个顶层工作流。
    5. 收集并打印所有唯一的 job 名称。
    """
    parser = argparse.ArgumentParser(description="从 GitHub Actions 工作流中解析实际运行的 job 名称。")
    parser.add_argument(
        "--repo-root",
        type=str,
        default=".",
        help="仓库的根目录路径。",
    )
    parser.add_argument(
        "--only-names",
        action="store_true",
        help="只输出发现的所有 Job 名称，不包含其他信息。",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not args.only_names:
        print(f"在目录中搜索工作流文件: {repo_root / '.github' / 'workflows'}")

    all_workflow_files = find_workflow_files(repo_root)
    all_job_names = set()  # 使用集合来自动去重

    # 筛选出顶层工作流：即那些不是被其他工作流调用的可复用工作流
    top_level_workflows = [wf for wf in all_workflow_files if not is_reusable_workflow(wf)]
    if not args.only_names:
        print(f"找到 {len(top_level_workflows)} 个顶层工作流进行解析。")

    # 遍历每个顶层工作流并解析其中的 job
    for workflow_file in top_level_workflows:
        if not args.only_names:
            print(f"正在解析: {workflow_file.relative_to(repo_root)}...")
        jobs = parse_workflow_jobs(workflow_file, repo_root, all_workflow_files)
        for name in jobs:
            all_job_names.add(name)

    # 打印最终结果
    if not args.only_names:
        print("\n--- 发现的所有 Job 名称 ---")
    for name in sorted(all_job_names):
        print(name)
    if not args.only_names:
        print("--------------------------\n")
