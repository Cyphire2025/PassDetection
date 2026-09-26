/**
 * ErrorBoundary — Light Theme
 */

"use client";

import React from "react";
import { Button } from "@/components/ui";
import { reportRenderError } from "@/lib/observability/render-errors";

interface ErrorBoundaryProps { children: React.ReactNode; fallback?: React.ReactNode; }
interface ErrorBoundaryState { hasError: boolean; reference: string | null; }

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  private reportGeneration = 0;
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, reference: null };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true, reference: null };
  }

  componentDidCatch(error: Error): void {
    const generation = ++this.reportGeneration;
    void reportRenderError(error, "shared").then((reference) => {
      if (generation === this.reportGeneration && this.state.hasError) this.setState({ reference });
    });
  }

  componentWillUnmount(): void { this.reportGeneration += 1; }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 p-10 text-center">
          <p className="mb-1 text-sm font-semibold text-red-700">Something went wrong</p>
          <p className="mb-5 text-xs text-slate-500">
            This screen could not be loaded. Try again, or contact support if it continues.
          </p>
          {this.state.reference && <p className="mb-4 text-xs text-slate-500">Support reference: {this.state.reference}</p>}
          <Button
            size="sm"
            variant="outline"
            onClick={() => { this.reportGeneration += 1; this.setState({ hasError: false, reference: null }); }}
          >
            Try again
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
