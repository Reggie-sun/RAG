import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      // onError 在新版本中已移除，错误会通过 mutation 的 onError 或组件级错误边界处理
    },
    mutations: {
      onError: (err: unknown) => {
        console.error("[Mutation Error]", err);
      },
    },
  },
});

// 全局错误处理函数
export const handleQueryError = (err: unknown) => {
  console.error("[Query Error]", err);
};

export const handleMutationError = (err: unknown) => {
  console.error("[Mutation Error]", err);
};