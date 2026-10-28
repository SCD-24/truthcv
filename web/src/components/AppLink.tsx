import { forwardRef } from "react";
import { Link, type LinkProps } from "react-router-dom";

const DANGEROUS_PATH = /\\|^\/\//;

function isSafePath(path: string): boolean {
  return path.startsWith("/") && !DANGEROUS_PATH.test(path);
}

function pathOf(to: LinkProps["to"]): string | null {
  if (typeof to === "string") return to;
  return typeof to.pathname === "string" ? to.pathname : null;
}

/**
 * The only router link the app uses (an ESLint rule bans importing `Link` or
 * `NavLink` elsewhere). react-router's `<Link>` renders absolute and
 * backslash targets as off-site hrefs by design, so this passes through only
 * same-origin paths: a leading single `/`, no backslash, no `//` prefix and
 * therefore no scheme. Any other target renders its children as plain text
 * with no href, so bad data never navigates or throws. Forwards its ref so MUI
 * `component={AppLink}` works.
 */
export const AppLink = forwardRef<HTMLAnchorElement, LinkProps>(
  function AppLink(props, ref) {
    const { to, children, className, style, title } = props;
    const path = pathOf(to);
    if (path === null || !isSafePath(path)) {
      return (
        <span
          className={className}
          style={style}
          title={title}
          aria-label={props["aria-label"]}
        >
          {typeof children === "function" ? null : children}
        </span>
      );
    }
    return <Link ref={ref} {...props} />;
  },
);
