interface SkeletonLineProps {
  w?: string;
}

export function SkeletonLine({ w = "100%" }: SkeletonLineProps) {
  return (
    <div
      className="h-4 rounded bg-slate-200/80 dark:bg-slate-800 animate-pulse"
      style={{ width: w }}
    />
  );
}
