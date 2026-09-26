import { expect, test } from "bun:test"
import {
  FALLBACK_REPO_CONTEXT_OPTIONS,
  RECOMMENDED_REPO_CONTEXT,
  bilingualLabel,
  repoContextChoices,
  repoContextDescription,
  repoContextIndexOf,
  repoContextLabel,
  repoContextStoredValue,
  repoContextSummary,
  repoContextValue,
  setupRepoContextField,
} from "./setup-repo-context"

/** 与 `config.options.repo_context` 同形：取值与 label 都来自后端（REPO_CONTEXT_MODES/LABELS）。 */
const backend = {
  value: "off",
  options: [
    { value: "off", label: "关闭 / Off" },
    { value: "tests", label: "仅测试文件 / Tests only" },
    { value: "tests+imports", label: "测试与依赖 / Tests + imports" },
  ],
}

test("the option list is whatever the backend sent, never a hard-coded set", () => {
  const future = {
    value: "tests",
    options: [
      { value: "tests", label: "仅测试文件 / Tests only" },
      // 后端将来加档位（或改名）时前端必须原样渲染，不能只认已知的三个值。
      { value: "full-tree", label: "整棵文件树 / Whole tree" },
    ],
  }
  expect(repoContextChoices(future).map((option) => option.value)).toEqual(["tests", "full-tree"])
  // 后端清单存在时，兜底表不参与。
  expect(repoContextChoices(backend).map((option) => option.value)).toEqual([
    "off",
    "tests",
    "tests+imports",
  ])
  // 旧后端 / options 缺块：兜底表兜住这一屏（与后端 REPO_CONTEXT_MODES 同序）。
  expect(repoContextChoices(undefined).map((option) => option.value)).toEqual([
    "off",
    "tests",
    "tests+imports",
  ])
  expect(repoContextChoices({ value: "off", options: [] })).toEqual(FALLBACK_REPO_CONTEXT_OPTIONS)
})

test("the backend's bilingual labels are split by ui_language", () => {
  const recommended = backend.options[2]
  expect(repoContextLabel(recommended, "zh-CN")).toBe("测试与依赖")
  expect(repoContextLabel(recommended, "en-US")).toBe("Tests + imports")
  expect(repoContextLabel(backend.options[1], "en-US")).toBe("Tests only")
  // 语言缺失按中文（与 isEn 的默认一致）。
  expect(repoContextLabel(backend.options[0], undefined)).toBe("关闭")
  // 单语 label（后端将来只给一种语言）原样返回，不拼空串。
  expect(bilingualLabel("Off", "en-US")).toBe("Off")
  expect(bilingualLabel("Off", "zh-CN")).toBe("Off")
  expect(bilingualLabel("", "en-US")).toBe("")
})

test("descriptions name the value and mark the recommended mode", () => {
  expect(repoContextDescription(backend.options[2], "zh-CN")).toContain("推荐")
  expect(repoContextDescription(backend.options[2], "en-US")).toContain("recommended")
  expect(repoContextDescription(backend.options[0], "zh-CN").startsWith("off · ")).toBe(true)
  expect(repoContextDescription(backend.options[0], "zh-CN")).toContain("零额外请求")
  expect(repoContextDescription(backend.options[1], "en-US")).toContain("test files")
  // 未知档位不编文案，只显示值本身。
  const unknown = { value: "full-tree", label: "整棵文件树 / Whole tree" }
  expect(repoContextDescription(unknown, "zh-CN")).toBe("full-tree")
  expect(repoContextDescription(unknown, "en-US")).toBe("full-tree")
})

test("the wizard preselects the stored value, falling back to the recommended mode", () => {
  expect(repoContextIndexOf(backend.options, "tests")).toBe(1)
  expect(repoContextIndexOf(backend.options, "tests+imports")).toBe(2)
  expect(repoContextIndexOf(backend.options, "off")).toBe(0)
  // 后端当前值不在清单里（旧配置 / 未来档位）→ 推荐档，而不是清单第一项 off。
  expect(repoContextIndexOf(backend.options, "nope")).toBe(2)
  expect(repoContextIndexOf(backend.options, undefined)).toBe(2)
  expect(RECOMMENDED_REPO_CONTEXT).toBe("tests+imports")
  // 清单里没有推荐档（后端改名）时退回第一项，不越界。
  expect(repoContextIndexOf([{ value: "off", label: "关闭 / Off" }], "nope")).toBe(0)
  expect(repoContextIndexOf([], "off")).toBe(0)
})

test("the selected value never goes out of bounds", () => {
  expect(repoContextValue(backend.options, 1)).toBe("tests")
  expect(repoContextValue(backend.options, 99)).toBe("tests+imports")
  expect(repoContextValue(backend.options, -3)).toBe("off")
  expect(repoContextValue([], 0)).toBe(RECOMMENDED_REPO_CONTEXT)
})

test("the setup payload always carries the mode shown on screen", () => {
  expect(setupRepoContextField("tests+imports")).toEqual({ repo_context: "tests+imports" })
  expect(setupRepoContextField("off")).toEqual({ repo_context: "off" })
  // 后端自己也做 strip/lower，前端先归一化，避免发出 " OFF " 这种载荷。
  expect(setupRepoContextField(" OFF ")).toEqual({ repo_context: "off" })
  // 空串（清单为空且无兜底，实际不可达）不发送 —— 后端把缺失当"保持不变"。
  expect(setupRepoContextField("")).toEqual({})
  expect(setupRepoContextField("   ")).toEqual({})
})

test("an untouched wizard submits the stored value, which defaults to tests+imports", () => {
  const submit = (current?: string) => {
    const list = repoContextChoices(backend)
    const index = repoContextIndexOf(list, current)
    return setupRepoContextField(repoContextValue(list, index))
  }
  // 后端已经落盘 tests+imports：用户一路 Enter，载荷仍是它。
  expect(submit("tests+imports")).toEqual({ repo_context: "tests+imports" })
  // 后端落盘 off：不动的助手里高亮 off，载荷也发 off（不会悄悄改回推荐档）。
  expect(submit("off")).toEqual({ repo_context: "off" })
  // 当前值缺失（旧后端快照）：预选推荐档 → 载荷 tests+imports，与后端默认一致。
  expect(submit(undefined)).toEqual({ repo_context: "tests+imports" })
})

test("the snapshot value is read from either of the backend's two shapes", () => {
  // config.snapshot.repo_context：纯字符串。
  expect(repoContextStoredValue("tests")).toBe("tests")
  // model.status.repo_context：{value, options}（App 会把它并进同一个快照对象）。
  expect(repoContextStoredValue({ value: "off", options: backend.options })).toBe("off")
  // 认不出来就空串 → 预选回落到推荐档，绝不猜一个档位。
  expect(repoContextStoredValue(undefined)).toBe("")
  expect(repoContextStoredValue(null)).toBe("")
  expect(repoContextStoredValue({})).toBe("")
  expect(repoContextStoredValue({ value: 3 })).toBe("")
  expect(repoContextStoredValue("")).toBe("")
})

test("the confirm page shows the localized label of the chosen mode", () => {
  expect(repoContextSummary(backend.options, "tests+imports", "zh-CN")).toBe("测试与依赖")
  expect(repoContextSummary(backend.options, "tests+imports", "en-US")).toBe("Tests + imports")
  expect(repoContextSummary(backend.options, "off", "en-US")).toBe("Off")
  // 值不在后端清单里但属于兜底表：用兜底表的双语 label，不显示裸值。
  const trimmed = [{ value: "tests", label: "仅测试文件 / Tests only" }]
  expect(repoContextSummary(trimmed, "off", "zh-CN")).toBe("关闭")
  // 两边都没有（不该发生）：退回值本身，绝不显示 undefined。
  expect(repoContextSummary(trimmed, "full-tree", "zh-CN")).toBe("full-tree")
})
