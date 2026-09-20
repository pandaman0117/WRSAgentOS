"""Mock 抓取 A，再放到 B；after 明确指定先后关系。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch() as system:
        pick = step("pick", object="A")
        place = step("place", object="A", target="B", after=pick)
        verify = step("verify", object="A", target="B", after=place)

        task = system.start(pick, place, verify)
        print("任务结果：", task.wait().state)
        print("A 的位置：", system.snapshot().data.objects["A"])
