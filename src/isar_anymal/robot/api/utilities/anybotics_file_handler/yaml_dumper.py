import yaml


class AnyboticsYamlDumper(yaml.Dumper):

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)
