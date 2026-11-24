"use client";

import { useCallback } from "react";
import {
  useMutation,
  type DefaultError,
  type MutateOptions,
  type MutationFunctionContext,
  type QueryClient,
  type UseMutationOptions,
  type UseMutationResult,
} from "@tanstack/react-query";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";

export type PrivateOperationOwner = ReturnType<typeof capturePrivateOperationOwner>;
type Envelope<T> = { variables: T } & (
  | { owner: PrivateOperationOwner; captureError?: never }
  | { owner?: never; captureError: unknown }
);

type PrivateMutationOptions<TData, TError, TVariables, TContext> = Omit<
  UseMutationOptions<TData, TError, TVariables, TContext>,
  "mutationFn" | "onMutate" | "onSuccess" | "onError" | "onSettled"
> & {
  mutationFn: (variables: TVariables, context: MutationFunctionContext, owner: PrivateOperationOwner) => Promise<TData>;
  onMutate?: (variables: NoInfer<TVariables>, context: MutationFunctionContext, owner: PrivateOperationOwner) => Promise<TContext> | TContext;
  onSuccess?: (data: TData, variables: NoInfer<TVariables>, result: TContext, context: MutationFunctionContext, owner: PrivateOperationOwner) => unknown;
  onError?: (error: TError, variables: NoInfer<TVariables>, result: TContext | undefined, context: MutationFunctionContext, owner: PrivateOperationOwner) => unknown;
  onSettled?: (data: TData | undefined, error: TError | null, variables: NoInfer<TVariables>, result: TContext | undefined, context: MutationFunctionContext, owner: PrivateOperationOwner) => unknown;
};

function envelope<T>(variables: T): Envelope<T> {
  try { return { variables, owner: capturePrivateOperationOwner() }; }
  catch (captureError) { return { variables, captureError }; }
}

function ownerOf<T>(value: Envelope<T>) {
  if (!value.owner) throw value.captureError;
  value.owner.assertCurrent();
  return value.owner;
}

function currentOwner<T>(value: Envelope<T>): PrivateOperationOwner | null {
  try { return ownerOf(value); } catch { return null; }
}

/**
 * Capture at mutate invocation, before TanStack awaits global or local onMutate.
 * Pass owner.requestConfig to HTTP and assertCurrent after callback-owned awaits.
 * Stale success becomes an error; stale error/settled effects are suppressed.
 * Global MutationCache callbacks see the internal envelope. Local callbacks and
 * public result.variables retain the caller's original variables and context.
 */
export function usePrivateMutation<TData = unknown, TError = DefaultError, TVariables = void, TContext = unknown>(
  options: PrivateMutationOptions<TData, TError, TVariables, TContext>,
  queryClient?: QueryClient,
): UseMutationResult<TData, TError, TVariables, TContext> {
  const mutation = useMutation<TData, TError, Envelope<TVariables>, TContext>({
    ...options,
    mutationFn: async (value, context) => {
      const owner = ownerOf(value);
      const data = await options.mutationFn(value.variables, context, owner);
      owner.assertCurrent();
      return data;
    },
    onMutate: async (value, context) => {
      const owner = ownerOf(value);
      const result = await options.onMutate?.(value.variables, context, owner);
      owner.assertCurrent();
      return result as TContext;
    },
    onSuccess: async (data, value, result, context) => {
      const owner = ownerOf(value);
      await options.onSuccess?.(data, value.variables, result, context, owner);
      owner.assertCurrent();
    },
    onError: async (error, value, result, context) => {
      const owner = currentOwner(value);
      if (owner) await options.onError?.(error, value.variables, result, context, owner);
    },
    onSettled: async (data, error, value, result, context) => {
      if (error === null) {
        const owner = ownerOf(value);
        await options.onSettled?.(data, error, value.variables, result, context, owner);
        owner.assertCurrent();
        return;
      }
      const owner = currentOwner(value);
      if (owner) await options.onSettled?.(data, error, value.variables, result, context, owner);
    },
  }, queryClient);

  const bindCallbacks = useCallback((callbacks?: MutateOptions<TData, TError, TVariables, TContext>): MutateOptions<TData, TError, Envelope<TVariables>, TContext> => ({
    onSuccess: (data, value, result, context) => {
      if (currentOwner(value)) callbacks?.onSuccess?.(data, value.variables, result, context);
    },
    onError: (error, value, result, context) => {
      if (currentOwner(value)) callbacks?.onError?.(error, value.variables, result, context);
    },
    onSettled: (data, error, value, result, context) => {
      if (currentOwner(value)) callbacks?.onSettled?.(data, error, value.variables, result, context);
    },
  }), []);
  const { mutate: run, mutateAsync: runAsync } = mutation;
  const mutate = useCallback((variables: TVariables, callbacks?: MutateOptions<TData, TError, TVariables, TContext>) => {
    run(envelope(variables), bindCallbacks(callbacks));
  }, [run, bindCallbacks]);
  const mutateAsync = useCallback((variables: TVariables, callbacks?: MutateOptions<TData, TError, TVariables, TContext>) => (
    runAsync(envelope(variables), bindCallbacks(callbacks))
  ), [runAsync, bindCallbacks]);

  return { ...mutation, variables: mutation.variables?.variables, mutate, mutateAsync } as UseMutationResult<TData, TError, TVariables, TContext>;
}
