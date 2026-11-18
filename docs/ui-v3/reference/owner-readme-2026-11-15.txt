I run an independent agent company.
Let's develop it separately and merge it at the end without affecting the original source.
Develop by branching from the current modifications.

Create a picture with a completely different aspect.
We need to make it exactly as shown in the image. If so, the current frontend library may not be enough. You can also use it by unloading a new library that can be created in this way.

===================================


The face-to-face section is the user-facing section.
The functions within it must be applied to all users and administrators, not separate from them.

The following points about the mission performance process are intended to be implemented.
1. 
First, there is a list of missions that have been given to date, and there is an Add Mission button at the top.
The mission list displays the title of the mission, a brief description of the mission, the current progress of the mission, and the number of issues currently raised, including the number awaiting the user's conclusion(Displayed in a specific color).   The version of the final output currently being produced must be indicated.  The completion date and time of the entire task must be indicated. The date of the next edition should be automatically displayed.  Display the progress of the current mission with colors and progress.
2. 
When you click the Add Mission button, the Add Mission window will appear. It is displayed in modal form. There is a task input field and a task start button. The mission input box contains text, documents, images, and GitHub addresses.
When the task start button is pressed, the general manager automatically creates and stores the title of the task according to the content of the task, creates a task workspace in the storage, connects to GitHub, and performs work there. 
If the user does not provide a GitHub address, a new repository is created in GitHub using the user's email account and connected to the repository. At this time, the user's approval is received.
3.
Once a mission begins, Move to the mission control panel.
in the left , There is a list of agents on this page, Agents are displayed in a hierarchical diagram(overview/diagram) showing hierarchical relationships, and the current flow status can be viewed by indicating each other with arrows.
When you click on any agent, a window where you can talk to him or her will appear on the right.
You can give instructions to the agent by entering a conversation in the chat window.
The conversation window displays the content of this agent's conversation with the selected agent. A list of agents who have had conversations with other agents is displayed.
The list displays the list of conversations that took place, including users, seniors, juniors, and fellow agents.
If you select one from this list, the contents of the conversation with that person will appear in the chat window.
the general manager takes overall command to complete the mission, including establishing a plan and replicating related data, research. We inquire with the user about the issues raised, and generally judge and resolve all processes ourselves.
There should be a window through which the general manager's thoughts and lower-level agents can see the associate governor and the reports received from him.
There is a history box below the content waiting for the user's conclusion, and there must be a list of candidates and the user's input. You must also be able to input images. Enter it and press the confirmation button.
Contents that the user responded to, said they saw, or gave an answer to are not displayed. Displayed only when all are displayed.
All conversations must be displayed by time. The time must be displayed. You must be able to copy the conversation. The copy button must display only an icon.
Depending on how you view the conversation, there is a way to display the assigned mission, the received mission, the mission performance process, and the contents of the report.(Other contents should also be displayed.). Another method is to display only the assigned mission, the content of the report received, the received mission, and the results.(For each agent).
It indicates whether or not each command is executed. It should be indicated in various ways, such as success, failure, in progress, etc., and should be indicated in color.

4.
The next tab is the version management window. The edition management system automatically stores editions as needed. Users should be able to download the output of the corresponding version from the list.
When you select the relevant edition, information related to the edition is displayed on the right, including updates to the edition.
Also, when you press the run button, the homepage starts up and shows the execution results.
5.
The preview window should immediately reflect any updates made during the current development process.
While working, the general manager stores the results in GitHub at certain stages. At this time, the service machine for previewing the current project is restarted so that the results are reflected in the current project.
6. 
While carrying out your mission, you must research not only internal data but also external websites to obtain all the data necessary to carry out your mission.  All imported materials must be learned by the entire company and used for mission purposes.  Additionally, all agents must evolve and develop on their own in the process of carrying out their missions. In other words, you need to gain experience and evolve, including updating your actual agent code. The general manager must be able to operate the company's system structure.
The general manager must be able to change even the structure of the company.

Next is the news window.
If the website addresses from which new messages are retrieved can be viewed, users should be able to add them as well.



==== ADMIN

It is a admin function.
Toggle self-renewal on or off should be in the settings.
Once you activate the setting, the update begins in earnest. If it is deactivated, it will be updated automatically during the project execution process.
If you activate this, the general manager will infinitely proceed with self-evolution, such as updating the company's structure and updating agents.
We continue to learn new external materials and develop. Also, verification is essential in the development process. Verification is carried out by obtaining data from a company specializing in inspection and updating the inspection and verification system.
Based on this, all updates are made, verified, and developed.
Version management must also be carried out.

Next is the model loader.
Registered models and agents must be accurately identified and constantly coordinated and connected to ensure that the necessary agents use the correct model.

next 
Occasionally, a small white board appears below the center of the screen.  The content is "updateable to block 9365236". get rid of this

Claude Code is in charge of code writing, and other architect design is handled by GPT. This is also done by GPT. When it comes to creative content, new ideas are discussed. Regarding data research and , Chupiti and Cloude work together to synthesize the results.


============

If you look at the picture, there is nothing like the following: 
In each screen, there is only the first tab and no content in the other tabs.
An example is task flow in mission control.
Please make the screens more specific. Also, please design and make it so that the user can change the face of the face in various ways, such as various colors and formats, and bright and dark aspects.
Please make it in various forms such as flat design, luminous design, pretty design, fancy design, etc.
Statements should be indicated with a “?” icon. Buttons usually display only icons. If possible, display it on one screen without scrolling. 
Aikents have icons that fit their missions as their default images.  After creating the image, please create another function document. Documentation about the agent function is missing.

One agent can be mobilized for multiple missions, which operate separately from each other. When the next mission is completed, he combines his experience and the execution process with the original agent and completes it. 
In version management of this GitHub version, it can be seen as the same as the process of branching from the basic stem for a different function and then merging it back into the basic stem.

Agents have another function.
It renews itself as experience accumulates.  It also includes implications of knowledge content.  The code update of the Tonna agent itself is also touching. At this time, agents are involved in nurturing other agents, and agents that verify performance are also included. If it is verified that the updated version has improved performance compared to the previous version, the new version will be used from next time.