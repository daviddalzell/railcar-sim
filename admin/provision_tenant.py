"""CLI: python -m admin.provision_tenant --slug=... --name=... --admin-email=..."""
import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision a new Waypoint tenant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python -m admin.provision_tenant \\
    --slug club-springfield \\
    --name "Springfield Model Railroad Club" \\
    --admin-email admin@springfield.com
""",
    )
    parser.add_argument("--slug",         required=True, help="Subdomain slug (e.g. club-springfield)")
    parser.add_argument("--name",         required=True, help="Display name for the tenant")
    parser.add_argument("--admin-email",  required=True, help="Email address for the admin user")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from admin.provisioning import provision_tenant
    try:
        result = provision_tenant(args.slug, args.name, args.admin_email)
        print("\nTenant provisioned successfully:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
