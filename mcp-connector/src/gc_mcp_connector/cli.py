"""Explicit installation/sign-in commands; serve reserves stdout for MCP frames."""

import argparse
import json
import logging
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import anyio
import httpx2

from . import __version__
from .artifacts import ArtifactClient
from .auth import Authorization
from .config import SCOPES, Config, ConnectorError
from .file_tools import LocalFileTools
from .oauth import AuthorizationAttempt, OAuthClient, browser_code
from .proxy import RemoteProxy
from .vault import WindowsCredentialLock, WindowsVault


async def run(args: argparse.Namespace) -> None:
    config = Config(args.origin)
    vault = WindowsVault(config.credential_key)
    # Resolve vault access before initiating any browser sign-in.
    vault.read()
    async with httpx2.AsyncClient(
        timeout=httpx2.Timeout(130, connect=10), follow_redirects=False, trust_env=False
    ) as http:
        oauth = OAuthClient(config, http)
        authorization = Authorization(oauth, vault, WindowsCredentialLock(config.credential_key))
        if args.command == "sign-in":
            await oauth.discover()
            attempt = AuthorizationAttempt.create()
            code = await browser_code(oauth, attempt, args.scopes)
            tokens = await oauth.exchange(code, attempt)
            await authorization.remember(tokens)
            print(
                "Signed in. Refresh authorization is stored in Windows Credential Manager.",
                file=sys.stderr,
            )
        elif args.command == "forget":
            await authorization.forget()
            print(
                "Local authorization cleared. Revoke the named connection in Administration > MCP to end server access.",
                file=sys.stderr,
            )
        elif args.command == "upload-pdf":
            path = Path(args.file)
            if not path.is_absolute():
                raise ConnectorError("Provide the exact absolute local PDF path.")
            result = await ArtifactClient(config, authorization, http).upload_pdf(
                path,
                allowed_paths=frozenset({path.resolve(strict=True)}),
                agency_id=args.agency,
                group_id=args.group,
            )
            print(json.dumps({**asdict(result), "business_ingestion": "not_started"}))
        elif args.command == "download":
            result = await ArtifactClient(config, authorization, http).download(
                args.artifact, destination=Path(args.destination)
            )
            print(json.dumps(result.as_dict()))
        elif args.command == "acknowledge-download":
            path = Path(args.file)
            if not path.is_absolute():
                raise ConnectorError("Provide the exact absolute local export path.")
            result = await ArtifactClient(config, authorization, http).acknowledge_existing(
                args.artifact, path=path, allowed_paths=frozenset({path.resolve(strict=True)})
            )
            print(json.dumps(result.as_dict()))
        else:
            selected = LocalFileTools(
                config,
                authorization,
                selected_paths=args.allow_file,
                download_directory=args.download_directory,
            )
            await RemoteProxy(config, authorization, file_tools=selected).serve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Global Connects MCP desktop connector")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--origin", required=True, help="Application origin, for example https://app.example.com"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sign_in = commands.add_parser(
        "sign-in", help="Authorize this desktop through the existing superadmin browser login"
    )
    sign_in.add_argument("--scopes", nargs="+", choices=sorted(SCOPES), default=["mcp:read"])
    serve = commands.add_parser("serve", help="Run the local stdio MCP connection")
    serve.add_argument(
        "--allow-file",
        action="append",
        default=[],
        help="Explicit absolute file path selected for transfer; repeat for more files",
    )
    serve.add_argument(
        "--download-directory", help="Existing absolute directory for new verified exports"
    )
    commands.add_parser("forget", help="Clear only this connector's local authorization")
    upload = commands.add_parser(
        "upload-pdf", help="Stage one explicitly selected PDF for an existing group"
    )
    upload.add_argument(
        "--file", required=True, help="Absolute path explicitly provided for this upload"
    )
    upload.add_argument("--agency", required=True, type=uuid.UUID)
    upload.add_argument("--group", required=True, type=uuid.UUID)
    download = commands.add_parser(
        "download", help="Save and verify an export without overwriting a file"
    )
    download.add_argument("--artifact", required=True)
    download.add_argument(
        "--destination", required=True, help="Explicit new absolute local filename"
    )
    acknowledge = commands.add_parser(
        "acknowledge-download",
        help="Verify a saved export and recover its delivery acknowledgement",
    )
    acknowledge.add_argument("--artifact", required=True)
    acknowledge.add_argument(
        "--file", required=True, help="Explicit absolute path of the previously saved export"
    )
    args = parser.parse_args()
    # SDK network errors can contain response text/URLs. Never let them print credentials.
    logging.disable(logging.CRITICAL)
    try:
        anyio.run(run, args)
    except ConnectorError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception:
        print(
            "Connector could not complete safely. Check installation and authorization, then retry sign-in.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
