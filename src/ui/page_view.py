import discord
from discord.ui import View
from ui.page_dropdown import PageDropdown
from model.help_model import CommandHelpGroup as HelpGroup

class PageView(View):
    def __init__(self, groups: list[HelpGroup]):
        super().__init__(timeout=None)
        self.groups = groups
        self.current = 0
        self.update_pagination()
        self.dropdown = PageDropdown(groups[0].commands)
        self.add_item(self.dropdown)
        

    def update_dropdown(self):
        self.dropdown.set_commands(self.groups[self.current].commands)

    def update_pagination(self):
        self.pagination.label = f"{self.current + 1} / {len(self.groups)}"
        self.pagination.disabled = True
        
    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = (self.current - 1) % len(self.groups)
        self.update_pagination()
        self.update_dropdown()
        await interaction.response.edit_message(embed=self.groups[self.current].embed, view=self)

    @discord.ui.button(label=f"1 / 1", style=discord.ButtonStyle.grey)
    async def pagination(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = (self.current + 1) % len(self.groups)
        self.update_pagination()
        self.update_dropdown()
        await interaction.response.edit_message(embed=self.groups[self.current].embed, view=self)

    @discord.ui.button(label="close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    
