import { Fragment } from "react";
import styles from "./thread.module.css";

/** A deliberately small Markdown renderer: model output never becomes HTML. */
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => part.startsWith("**")
    ? <strong key={index}>{part.slice(2, -2)}</strong> : part.startsWith("`")
      ? <code key={index}>{part.slice(1, -1)}</code> : <Fragment key={index}>{part}</Fragment>);
}

export function MessageContent({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/);
  return <div className={styles.markdown}>{blocks.map((block, index) => {
    const lines = block.split("\n");
    if (lines.length > 1 && lines.every((line) => /^\s*[-*]\s/.test(line))) return <ul key={index}>{lines.map((line, row) => <li key={row}>{inline(line.replace(/^\s*[-*]\s/, ""))}</li>)}</ul>;
    if (lines.length > 1 && lines.every((line) => /^\s*\d+[.)]\s/.test(line))) return <ol key={index}>{lines.map((line, row) => <li key={row}>{inline(line.replace(/^\s*\d+[.)]\s/, ""))}</li>)}</ol>;
    if (lines.length > 2 && lines[0].includes("|") && /^\s*\|?\s*:?-{3}/.test(lines[1])) {
      const cells = (line: string) => line.replace(/^\s*\||\|\s*$/g, "").split("|").map((cell) => cell.trim());
      return <div className={styles.tableWrap} key={index}><table><thead><tr>{cells(lines[0]).map((cell, column) => <th key={column}>{inline(cell)}</th>)}</tr></thead><tbody>{lines.slice(2).map((line, row) => <tr key={row}>{cells(line).map((cell, column) => <td key={column}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>;
    }
    if (/^#{1,3}\s/.test(block)) return <h3 key={index}>{inline(block.replace(/^#{1,3}\s/, ""))}</h3>;
    return <p key={index}>{inline(block)}</p>;
  })}</div>;
}
