import json
import os
import argparse
from pprint import pprint

import django
from django.apps import apps
from django.core import serializers
from django.db.models import ForeignKey, ManyToManyField, OneToOneField

import yaml

arg_parser = argparse.ArgumentParser(
    prog="Record To Fixture",
    description="Convert Models Record To Fixtrue",
)

arg_parser.add_argument(
    "-s",
    "--setting",
    type=str,
    help="setting file of django project: my_project.settings",
)
arg_parser.add_argument(
    "-f",
    "--file",
    type=str,
    help="yaml file to as input for tool: file.yaml",
)
arg_parser.add_argument(
    "-o",
    "--output",
    type=str,
    help="output file to store fixtrues",
)

args = arg_parser.parse_args()


os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.setting)
django.setup()

yaml_file = open(args.file, "r").read()


# Util Input
target_models = yaml.safe_load(yaml_file).get("models", {})

# Save Output
items = []


def pk_to_fixture(model, lookup_key, pks) -> list[dict]:
    """
    Serialize a queryset of model records by lookup keys.
    """
    queryset = model.objects.filter(**{lookup_key: pks})
    data = qs_to_fixture(queryset)
    return data


def qs_to_fixture(qs) -> list[dict]:
    data = serializers.serialize("json", qs)
    return json.loads(data)


def find_all_relationships_for_pk(target_model, pk) -> dict[list]:
    related_fixture = []
    for model in apps.get_models():
        if model == target_model:
            # Skip the target model itself
            continue

        # Find fields in the other models that reference the target model
        for field in model._meta.get_fields():
            if not isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)):  # noqa: SIM102
                continue
            if field.related_model != target_model:
                continue

            # Search for records in this model that reference the given PK
            related_qs = model.objects.filter(**{field.name: pk})
            fixture = qs_to_fixture(related_qs)
            related_fixture.extend(fixture)

    return related_fixture


# Loop through the target models and generate the fixtures
for model_key, info in target_models.items():
    # Get the app_label and model_name
    app_label, model_name = model_key.split(".")
    Model = apps.get_model(app_label, model_name)

    # Get the list of primary keys
    pks = info.get("pks", [])
    lookup_key = info.get("lookup", [])
    # Serialize the main records
    data = pk_to_fixture(Model, lookup_key, pks)

    # Process related models specified in "follow-relations"
    for item in data:
        fields = item.get("fields", {})
        for follow_field in info.get("follow-relations", []):
            if follow_field not in fields:
                continue

            # Get the primary key of the related record
            related_pk = fields[follow_field]

            # Get the related model
            field = Model._meta.get_field(follow_field)
            related_model = field.related_model

            # Serialize the related model's record
            related_data = pk_to_fixture(related_model, "pk__in", [related_pk])
            if related_data:
                items.extend(related_data)

    # Load records that has a relation to this item
    if info.get("load-relations", False):
        for pk in pks:
            related_fixture = find_all_relationships_for_pk(Model, pk)
            items.extend(related_fixture)

    items.extend(data)

    print(f"Fixture created for {model_key}")


# Write the serialized data to a fixture file
fixture_filename = args.output
with open(fixture_filename, "w") as f:
    json.dump(items, f, indent=4)  # Write the fixture as a JSON array
