import { Card } from "../common/card";
import { Button } from "../ui/button";
import { Tag } from "../common/tag";
import { cn } from "../../lib/utils";

export interface FeedbackTagOption {
  id: string;
  label: string;
  text: string;
  description?: string;
  recommended?: boolean;
}

interface FeedbackFormProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  isVisible: boolean;
  isSubmitting?: boolean;
  focusMode?: boolean;
  history?: string | null;
  selectedTags?: string[];
  tagOptions?: FeedbackTagOption[];
}

export function FeedbackForm({
  value,
  onChange,
  onSubmit,
  disabled = false,
  isVisible,
  isSubmitting = false,
  focusMode = false,
  history,
  selectedTags = [],
  tagOptions = [],
}: FeedbackFormProps) {
  if (!isVisible) {
    return null;
  }

  const characterCount = value.trim().length;
  const selectedLabels = tagOptions
    .filter((option) => selectedTags.includes(option.id))
    .map((option) => option.label);
  const charHint =
    selectedLabels.length > 0
      ? `已选择：${selectedLabels.join("，")}。${characterCount < 20 ? "再补充具体细节会更好。" : "欢迎继续补充更具体的问题。"}`
      : characterCount < 20
        ? "建议尽量具体，例如请输入 20 字以上的描述。"
        : "描述越具体，下一次改进越明显。";

  const placeholder =
    "例如：没有引用治疗章节；缺少具体页码；只解释定义没有提到方案…";
  const historyLines = (history ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <Card
      title="回答不满意？"
      className={cn(
        "transition-all duration-300",
        focusMode && "shadow-lg shadow-[#835dff]/20",
      )}
      contentClassName="space-y-4"
    >
      <p className={cn("text-sm leading-relaxed text-[#4c2d7a]/80", focusMode && "text-base")}>
        直接写下这轮回答的问题，我们会记住这些反馈并在下一次生成时重点改进，直到你满意为止。
      </p>

      {tagOptions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-[#51336f]">常见问题 · 自动识别出的关切点</p>
          <div className="flex flex-wrap gap-2">
            {tagOptions.map((option) => {
              const isSelected = selectedTags.includes(option.id);
              return (
                <Tag
                  key={option.id}
                  asSpan
                  active={isSelected}
                  className={cn(
                    "cursor-default select-none px-3.5 py-1.5 text-xs",
                    !isSelected && "bg-white/50 text-[#7a598f] border-white/50",
                  )}
                >
                  {option.label}
                  {option.recommended && (
                    <span className="ml-1 text-[10px] font-bold text-[#ffe9ab] drop-shadow">
                      荐
                    </span>
                  )}
                </Tag>
              );
            })}
          </div>
        </div>
      )}

      {selectedTags.length > 0 && (
        <div className="space-y-3 rounded-3xl border border-white/60 bg-gradient-to-r from-[#fff6ff] via-[#fbe5ff] to-[#f3d0ff] p-4 text-sm text-[#4c2d7a] shadow-inner shadow-[#caa9ff]/30">
          {tagOptions
            .filter((option) => selectedTags.includes(option.id))
            .map((option) => (
              <div
                key={option.id}
                className="rounded-2xl bg-white/70 px-4 py-2 text-sm leading-relaxed text-[#4c2d7a] shadow-sm shadow-white/40"
              >
                <p className="font-semibold">{option.label}</p>
                <p className="text-xs text-[#6b437f]">{option.text}</p>
              </div>
            ))}
        </div>
      )}

      {historyLines.length > 0 && (
        <div
          className={cn(
            "rounded-2xl bg-white/70 p-3 text-xs text-[#51336f]",
            "dark:bg-white/10 dark:text-slate-200",
            focusMode && "text-sm",
          )}
        >
          <p className="mb-2 font-semibold">已记录的反馈</p>
          <ul className="list-disc space-y-1 pl-4 marker:text-[#a26bde]">
            {historyLines.map((line, index) => (
              <li key={`${line}-${index}`}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={focusMode ? 4 : 3}
        className={cn(
          "w-full resize-none rounded-2xl border border-white/50 bg-white/80 px-4 py-3 text-sm text-[#2b174d]",
          "placeholder:text-[#a084c5] focus:outline-none focus:ring-2 focus:ring-[#a26bde]/40",
          "dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-100 dark:placeholder:text-slate-400",
          focusMode && "text-base py-4",
        )}
        disabled={disabled}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-xs text-[#806296] dark:text-slate-400">
          {charHint}
        </span>
        <Button
          type="button"
          onClick={onSubmit}
          disabled={disabled || !value.trim()}
          className="w-full whitespace-nowrap sm:w-auto"
        >
          {isSubmitting ? "重新生成中…" : "带着反馈重新生成"}
        </Button>
      </div>
    </Card>
  );
}
