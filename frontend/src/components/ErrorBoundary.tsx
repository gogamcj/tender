import { Component, type ReactNode } from "react";

/** 화면 하나에서 예상치 못한 오류가 나도 빈 화면 대신 안내를 보여 준다. 다른 메뉴로 가면 초기화된다. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-medium">이 화면을 표시하는 중 오류가 났습니다. 저장된 자료는 바뀌지 않았습니다.</p>
        <p className="mt-1 text-xs">다른 메뉴로 이동하거나 새로고침해 보세요. 계속되면 아래 내용을 알려 주세요.</p>
        <pre className="mt-2 whitespace-pre-wrap text-xs">{this.state.error.message}</pre>
        <button className="btn-secondary mt-2" onClick={() => window.location.reload()}>
          새로고침
        </button>
      </div>
    );
  }
}
