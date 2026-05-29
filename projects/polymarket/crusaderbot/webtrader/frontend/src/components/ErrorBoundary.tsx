import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/**
 * App-level error boundary. A render error in any page used to crash the whole
 * React tree → blank white screen (e.g. a null field dereference). This catches
 * it and shows a recoverable fallback instead, so one bad field never blanks
 * the entire app.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || "Something went wrong." };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surfaces in the browser console + any console-capturing telemetry.
    console.error("ErrorBoundary caught a render error:", error, info.componentStack);
  }

  private handleReload = () => {
    this.setState({ hasError: false, message: "" });
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="text-3xl">⚠️</div>
        <h1 className="font-hud text-sm font-bold tracking-widest uppercase text-gold">
          Something broke on this screen
        </h1>
        <p className="text-ink-3 text-xs font-mono max-w-sm break-words">{this.state.message}</p>
        <button
          type="button"
          onClick={this.handleReload}
          className="mt-2 px-4 py-2 rounded border border-gold/40 bg-gold/10 text-gold text-[10px] font-bold tracking-widest uppercase hover:bg-gold/20"
        >
          Reload
        </button>
      </div>
    );
  }
}
