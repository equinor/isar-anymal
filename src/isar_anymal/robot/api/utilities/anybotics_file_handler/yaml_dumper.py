import yaml


class AnyboticsYamlDumper(yaml.Dumper):

    def increase_indent(self, flow=False, indentless=False):
        return super(AnyboticsYamlDumper, self).increase_indent(flow, False)
